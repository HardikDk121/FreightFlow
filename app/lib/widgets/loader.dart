import 'package:flutter/material.dart';

import '../api/api_client.dart';
import 'common.dart';

/// Loads data once, then shows it. Handles the loading, error-with-retry and pull-to-refresh
/// states so each screen only describes what to load and how to show it.
class Loader<T> extends StatefulWidget {
  const Loader({super.key, required this.load, required this.errorTitle, required this.builder, this.cacheKey});

  final Future<T> Function() load;
  final String errorTitle;

  /// Stale-while-revalidate: with a key, the last result for it is shown at once while a fresh
  /// one loads behind it, instead of a skeleton every time the screen opens.
  final String? cacheKey;

  /// Must return a scrollable (a ListView) so pull-to-refresh works.
  final Widget Function(BuildContext context, T data) builder;

  @override
  State<Loader<T>> createState() => LoaderState<T>();
}

class LoaderState<T> extends State<Loader<T>> {
  /// Last results by cache key, for this app session only. Cleared on sign-out.
  static final Map<String, Object?> _cache = {};

  static void clearCache() => _cache.clear();

  T? _data;
  String? _error;
  bool _loaded = false;

  /// True while a refresh runs behind data already shown.
  bool _refreshing = false;

  @override
  void initState() {
    super.initState();
    final key = widget.cacheKey;
    if (key != null && _cache.containsKey(key)) {
      _data = _cache[key] as T;
      _loaded = true;
    }
    reload();
  }

  /// Fetch again. Screens call this through a GlobalKey after something changed.
  Future<void> reload() async {
    setState(() {
      _error = null;
      _refreshing = _loaded;
    });
    try {
      final data = await widget.load();
      if (!mounted) return;
      if (widget.cacheKey != null) _cache[widget.cacheKey!] = data;
      setState(() {
        _data = data;
        _loaded = true;
        _refreshing = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _refreshing = false);
      // With data already on screen, keep it and say the refresh failed rather than blanking it.
      if (_loaded) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text('Could not refresh: ${e.message}')));
      } else {
        setState(() => _error = e.message);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return MessageView(
        icon: Icons.cloud_off_outlined,
        title: widget.errorTitle,
        body: _error!,
        actionLabel: 'Try again',
        onAction: reload,
      );
    }
    if (!_loaded) return const SkeletonList();
    return Stack(
      children: [
        RefreshIndicator(onRefresh: reload, child: widget.builder(context, _data as T)),
        if (_refreshing)
          const Positioned(top: 0, left: 0, right: 0, child: LinearProgressIndicator(minHeight: 2)),
      ],
    );
  }
}
