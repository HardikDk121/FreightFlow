import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import 'resource.dart';
import 'resource_form_screen.dart';

class MasterDataScreen extends StatelessWidget {
  const MasterDataScreen({super.key});

  static final _resources = [parties, itemTypes, trucks];

  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: _resources.length,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Master data'),
            bottom: TabBar(
              labelColor: Palette.primary,
              unselectedLabelColor: Palette.onSurfaceMuted,
              indicatorColor: Palette.primary,
              dividerColor: Palette.outline,
              labelStyle: Theme.of(context).textTheme.labelMedium,
              tabs: [for (final r in _resources) Tab(text: r.plural)],
            ),
          ),
          body: TabBarView(children: [for (final r in _resources) ResourceList(resource: r)]),
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
      MaterialPageRoute(builder: (_) => ResourceFormScreen(resource: widget.resource, row: row)),
    );
    if (saved == true && mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final canEdit = context.select<Session, bool>((s) => s.user?.canEditMasterData ?? false);
    return Scaffold(
      floatingActionButton: canEdit
          ? FloatingActionButton.extended(
              heroTag: widget.resource.path,
              onPressed: _openForm,
              icon: const Icon(Icons.add),
              label: Text('Add ${widget.resource.singular}'),
            )
          : null,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: TextField(
              controller: _search,
              onChanged: _onSearchChanged,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: 'Search ${widget.resource.plural.toLowerCase()}',
                prefixIcon: const Icon(Icons.search),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Align(
              alignment: Alignment.centerLeft,
              child: FilterChip(
                label: const Text('Show inactive'),
                selected: _includeInactive,
                shape: const StadiumBorder(side: BorderSide(color: Palette.outline)),
                backgroundColor: Palette.surface,
                selectedColor: Palette.primaryContainer,
                onSelected: (value) {
                  _includeInactive = value;
                  _load();
                },
              ),
            ),
          ),
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
      return MessageView(
        icon: Icons.inbox_outlined,
        title: 'No ${widget.resource.plural.toLowerCase()} yet',
        body: canEdit ? 'Add the first one with the button below.' : 'An admin or manager can add them.',
      );
    }
    final text = Theme.of(context).textTheme;
    final status = StatusColors.of(context);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
        itemCount: rows.length,
        separatorBuilder: (_, __) => const SizedBox(height: 12),
        itemBuilder: (_, i) {
          final row = rows[i];
          final subtitle = widget.resource.subtitle(row);
          return AppCard(
            child: ListTile(
              minVerticalPadding: 16,
              title: Text(row[widget.resource.titleKey] as String, style: text.titleMedium),
              subtitle: subtitle.isEmpty ? null : Text(subtitle, style: text.bodyMedium),
              trailing: row['is_active'] as bool
                  ? null
                  : StatusChip('Inactive', background: Palette.background, foreground: status.muted),
              onTap: canEdit ? () => _openForm(row) : null,
            ),
          );
        },
      ),
    );
  }
}
