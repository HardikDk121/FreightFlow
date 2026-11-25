# Deploying this version to the existing EC2 server

These steps update the server that your DuckDNS name points to. They keep the same stack (Docker
Compose: PostgreSQL 16 and the FastAPI API), the same database volume and the same address.

I have not seen the server itself. Before starting, check two things on it:

1. **How the API runs today.** If it runs with `docker compose` from a folder holding this project,
   follow the steps as written. If it runs another way (systemd, plain `uvicorn`, PM2), stop and ask:
   the steps below assume Compose.
2. **Whether something already serves HTTPS** (nginx, Caddy, a load balancer). Run
   `sudo ss -ltnp | grep -E ':80|:443|:8000'`. If nginx or Caddy is listening on 443, keep it and skip
   the "Optional HTTPS" section.

## 1. Back up first (required)

The API container applies database migrations when it starts. This version adds migrations up to
`0013` (0013 also rewrites stored Indian phone numbers to their 10 digits); some cannot be undone (`0008`, `0010`), so the backup is the way back.

```sh
cd /path/to/freightflow                      # the folder with docker-compose.yml on the server
mkdir -p ~/backups
docker compose exec -T db pg_dump -U postgres -Fc freightflow > ~/backups/freightflow-$(date +%F-%H%M).dump
ls -lh ~/backups                              # the file must not be empty
cp .env ~/backups/env-$(date +%F)             # your settings; keep it private
tar czf ~/backups/app-$(date +%F).tgz --exclude=.env .   # the current code, to roll back to
```

Check which migration the database is on, so you know what will run:

```sh
docker compose exec -T db psql -U postgres -d freightflow -c "SELECT version_num FROM alembic_version;"
```

## 2. Put the new code in place

Copy the ZIP to the server (for example `scp freightflow.zip ec2-user@your-name.duckdns.org:~`), then:

```sh
cd /path/to
unzip -o ~/freightflow.zip            # unpacks into ./freightflow, keeping your .env (it is not in the ZIP)
cd freightflow
```

## 3. Add the new settings to `.env`

Open `.env` and add the lines from the "Production settings" block at the end of `.env.example`. To
keep the server behaving exactly as today, use:

```
FF_ENV=production
FF_API_BIND=0.0.0.0
FF_HTTPS=false
FF_FORWARDED_ALLOW_IPS=127.0.0.1
```

Also check `FF_JWT_SECRET` is a real random value of at least 32 characters. In production the API
now refuses to start with the example value. Generate one with
`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing it signs everyone out once.

## 4. Rebuild and restart

```sh
docker compose build api
docker compose up -d
docker compose logs -f api            # wait for "Application startup complete", then Ctrl+C
```

## 5. Check it works through the DuckDNS address

```sh
curl -s http://your-name.duckdns.org:8000/health          # {"status":"ok"}   (or https://... if behind HTTPS)
curl -s -o /dev/null -w "%{http_code}\n" http://your-name.duckdns.org:8000/docs   # 404 in production
curl -sI http://your-name.duckdns.org:8000/health | grep -i x-content-type-options  # nosniff
```

Then sign in from the app and open an LR, a trip and Analytics.

## Optional HTTPS for the DuckDNS name

Only if nothing else serves HTTPS on the server. Passwords and sign-in tokens travel in every
request, so plain HTTP on port 8000 lets anyone on the same network read them. This is the most
important remaining risk if the API is reached over plain HTTP today.

1. In the EC2 security group, open ports 80 and 443 (Let's Encrypt needs 80).
2. In `.env`:
   ```
   FF_DOMAIN=your-name.duckdns.org
   FF_API_BIND=127.0.0.1
   FF_HTTPS=true
   FF_FORWARDED_ALLOW_IPS=*
   ```
   With `FF_API_BIND=127.0.0.1`, port 8000 is no longer reachable from outside, which is what makes
   trusting the proxy's forwarded address (`*`) safe.
3. `docker compose --profile https up -d`, then `curl -s https://your-name.duckdns.org/health`.
4. Point the app at `https://your-name.duckdns.org` (build it with `--dart-define=API_BASE_URL=...`),
   then close port 8000 in the security group.

## Rolling back

```sh
cd /path/to && rm -rf freightflow && mkdir freightflow && tar xzf ~/backups/app-<date>.tgz -C freightflow
cd freightflow && cp ~/backups/env-<date> .env
docker compose stop api
docker compose exec -T db pg_restore -U postgres -d freightflow --clean --if-exists < ~/backups/freightflow-<date>.dump
docker compose up -d --build
```

## Daily job

Collection tasks, payment reminders and scheduled reports run once a day. Add to the server's crontab
(`crontab -e`):

```
30 6 * * * cd /path/to/freightflow && docker compose run --rm api python -m app.jobs daily >> ~/freightflow-daily.log 2>&1
```
