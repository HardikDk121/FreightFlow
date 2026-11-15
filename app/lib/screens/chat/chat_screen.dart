import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../theme/app_theme.dart';

class _Message {
  const _Message(this.text, {required this.mine, this.lrNumbers = const [], this.failed = false});

  final String text;
  final bool mine;
  final List<String> lrNumbers;
  final bool failed;
}

const _examples = [
  'What is pending for Surat?',
  'What came today?',
  'Which goods have waited more than 3 days?',
];

/// Ask about pending goods, arrivals and LR status in plain words. The assistant only reads.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<_Message> _messages = [];
  bool _waiting = false;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _add(_Message message) {
    setState(() => _messages.add(message));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _send(String question) async {
    final text = question.trim();
    if (text.isEmpty || _waiting) return;
    _input.clear();
    _add(_Message(text, mine: true));
    setState(() => _waiting = true);
    try {
      final reply = await context.read<ApiClient>().post('/chat', {'message': text}) as Map<String, dynamic>;
      if (!mounted) return;
      _add(_Message(
        reply['answer'] as String,
        mine: false,
        lrNumbers: (reply['lr_numbers'] as List).cast<String>(),
      ));
    } on ApiException catch (e) {
      if (mounted) _add(_Message(e.message, mine: false, failed: true));
    } finally {
      if (mounted) setState(() => _waiting = false);
    }
  }

  Widget _bubble(_Message message) {
    final text = Theme.of(context).textTheme;
    final color = message.failed
        ? Palette.errorContainer
        : message.mine
            ? Palette.primaryContainer
            : Palette.surface;
    return Align(
      alignment: message.mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(12),
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.82),
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(12),
          border: message.mine ? null : Border.all(color: Palette.outline),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(message.text, style: text.bodyLarge),
            if (message.lrNumbers.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                'From records: ${message.lrNumbers.join(', ')}',
                style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Ask')),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: _messages.isEmpty
                  ? ListView(
                      padding: const EdgeInsets.all(16),
                      children: [
                        Text('Ask about your goods', style: text.titleMedium),
                        const SizedBox(height: 4),
                        Text('I can look things up. I cannot change anything.', style: text.bodyMedium),
                        const SizedBox(height: 16),
                        for (final example in _examples)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: OutlinedButton(onPressed: () => _send(example), child: Text(example)),
                          ),
                      ],
                    )
                  : ListView(
                      controller: _scroll,
                      padding: const EdgeInsets.all(16),
                      children: [for (final m in _messages) _bubble(m)],
                    ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _input,
                      textInputAction: TextInputAction.send,
                      onSubmitted: _send,
                      decoration: const InputDecoration(hintText: 'Type a question'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    tooltip: 'Send',
                    onPressed: _waiting ? null : () => _send(_input.text),
                    icon: _waiting
                        ? const SizedBox.square(dimension: 20, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.arrow_upward),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
