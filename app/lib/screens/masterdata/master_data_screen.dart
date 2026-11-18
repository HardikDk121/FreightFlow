import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import 'resource.dart';
import 'resource_form_screen.dart';

/// Tabs of add-and-edit lists. Used for master data and for the rate matrix.
class MasterDataScreen extends StatefulWidget {
  const MasterDataScreen({super.key, required this.title, required this.intro, required this.resources});

  /// Parties, item types and trucks.
  MasterDataScreen.masterData({super.key})
      : title = 'Master data',
        intro = 'Your people, goods and fleet. One place.',
        resources = [parties, itemTypes, trucks];

  final String title;
  final String intro;
  final List<Resource> resources;

  @override
  State<MasterDataScreen> createState() => _MasterDataScreenState();
}

class _MasterDataScreenState extends State<MasterDataScreen> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.title)),
        body: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  PageIntro(widget.intro),
                  Segmented<int>(
                    options: {for (var i = 0; i < widget.resources.length; i++) i: widget.resources[i].plural},
                    value: _tab,
                    onChanged: (i) => setState(() => _tab = i),
                  ),
                ],
              ),
            ),
            Expanded(
              // Every tab stays alive, so switching back keeps its search and scroll position.
              child: IndexedStack(
                index: _tab,
                children: [for (final r in widget.resources) ResourceList(resource: r)],
              ),
            ),
          ],
        ),
      );
}

/// Searchable list of one resource. Admins and managers can add and edit.
class ResourceList extends StatefulWidget {
  const ResourceList({super.key, required this.resource});

  final Resource resource;

  @override
  State<ResourceList> createState() => _ResourceListState();
}

class _ResourceListState extends State<ResourceList> with AutomaticKeepAliveClientMixin {
  final _search = TextEditingController();
  Timer? _debounce;
  List<JsonRow>? _rows;
  String? _error;
  bool _includeInactive = false;
  int _request = 0;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final request = ++_request;
    setState(() {
      _rows = null;
      _error = null;
    });
    final q = _search.text.trim();
    try {
      final data = await context.read<ApiClient>().get(widget.resource.path, query: {
        'limit': '200',
        if (q.isNotEmpty) 'q': q,
        if (_includeInactive) 'include_inactive': 'true',
      });
      // A newer search may have started while this one was in flight.
      if (!mounted || request != _request) return;
      setState(() => _rows = (data as List).cast<JsonRow>());
    } on ApiException catch (e) {
      if (!mounted || request != _request) return;
      setState(() => _error = e.message);
    }
  }

  void _onSearchChanged(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), _load);
  }

  Future<void> _openForm([JsonRow? row]) async {
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) =>
            widget.resource.customForm?.call(row) ?? ResourceFormScreen(resource: widget.resource, row: row),
      ),
    );
    if (saved == true && mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final canEdit = context.select<Session, bool>((s) => s.user?.canEditMasterData ?? false);
    final text = Theme.of(context).textTheme;
    return Scaffold(
      bottomNavigationBar: canEdit
          ? BottomBar(
              children: [BusyButton(icon: Icons.add, label: 'Add ${widget.resource.singular}', onPressed: _openForm)],
            )
          : null,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 4, 20, 10),
            child: TextField(
              controller: _search,
              onChanged: _onSearchChanged,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: 'Search ${widget.resource.plural.toLowerCase()}',
                prefixIcon: const Icon(Icons.search),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
                enabledBorder:
                    OutlineInputBorder(borderRadius: BorderRadius.circular(999), borderSide: BorderSide.none),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Align(
              alignment: Alignment.centerLeft,
              child: FilterChip(
                label: const Text('Show inactive'),
                selected: _includeInactive,
                labelStyle: text.labelMedium!.copyWith(color: _includeInactive ? Palette.onInk : Palette.onSurface),
                side: BorderSide.none,
                backgroundColor: Palette.surface,
                selectedColor: Palette.ink,
                onSelected: (value) {
                  _includeInactive = value;
                  _load();
                },
              ),
            ),
          ),
          const SizedBox(height: 8),
          Expanded(child: _body(canEdit)),
        ],
      ),
    );
  }

  Widget _body(bool canEdit) {
    if (_error != null) {
      return MessageView(
        icon: Icons.cloud_off_outlined,
        title: 'Could not load ${widget.resource.plural.toLowerCase()}',
        body: _error!,
        actionLabel: 'Try again',
        onAction: _load,
      );
    }
    final rows = _rows;
    if (rows == null) return const SkeletonList();
    if (rows.isEmpty) {
      final plural = widget.resource.plural.toLowerCase();
      return ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
        children: [
          MessageView(
            card: true,
            icon: widget.resource.icon,
            title: _search.text.trim().isEmpty ? 'No $plural yet' : 'No matching $plural',
            body: canEdit
                ? 'Add your first ${widget.resource.singular} with the button below.'
                : 'An admin or manager can add them.',
          ),
        ],
      );
    }
    final text = Theme.of(context).textTheme;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
        itemCount: rows.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, i) {
          final row = rows[i];
          final subtitle = widget.resource.subtitle(row);
          return AppCard(
            onTap: canEdit ? () => _openForm(row) : null,
            padding: const EdgeInsets.all(18),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(row[widget.resource.titleKey] as String, style: text.titleMedium),
                      if (subtitle.isNotEmpty) ...[
                        const SizedBox(height: 4),
                        Text(subtitle, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
                      ],
                    ],
                  ),
                ),
                if (!(row['is_active'] as bool)) StatusChip.tone('Inactive', Tone.neutral),
                if (canEdit) const Icon(Icons.chevron_right, color: Palette.onSurfaceMuted),
              ],
            ),
          );
        },
      ),
    );
  }
}
