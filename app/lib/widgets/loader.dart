import 'package:flutter/material.dart';

import '../api/api_client.dart';
import 'common.dart';

/// Loads data once, then shows it. Handles the loading, error-with-retry and pull-to-refresh
/// states so each screen only describes what to load and how to show it.
class Loader<T> extends StatefulWidget {
  const Loader({super.key, required this.load, required this.errorTitle, required this.builder});

  final Future<T> Function() load;
  final String errorTitle;

  /// Must return a scrollable (a ListView) so pull-to-refresh works.
  final Widget Function(BuildContext context, T data) builder;

  @override
  State<Loader<T>> createState() => LoaderState<T>();
}

class LoaderState<T> extends State<Loader<T>> {
  T? _data;
  String? _error;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    reload();
  }

  /// Fetch again. Screens call this through a GlobalKey after something changed.
  Future<void> reload() async {
    setState(() => _error = null);
    try {
      final data = await widget.load();
      if (!mounted) return;
      setState(() {
        _data = data;
        _loaded = true;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
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
    return RefreshIndicator(onRefresh: reload, child: widget.builder(context, _data as T));
  }
}
