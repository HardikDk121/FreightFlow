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

const _starters = [
  'What is pending?',
  'What was booked today?',
  'Which goods have waited more than 3 days?',
  'Which trucks are on the road?',
];

/// Ask about LRs, pending goods, bookings and trucks in plain words. The assistant only reads.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<_Message> _messages = [];
  List<String> _suggestions = _starters;

  /// The LR the conversation is about, so "and its weight?" needs no number.
  String? _contextLr;
  bool _waiting = false;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _scrollToEnd() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(
            _scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250),
            curve: Curves.easeOut,
          );
        }
      });

  Future<void> _send(String question) async {
    final text = question.trim();
    if (text.isEmpty || _waiting) return;
    _input.clear();
    setState(() {
      _messages.add(_Message(text, mine: true));
      _waiting = true;
    });
    _scrollToEnd();
    try {
      final reply = await context.read<ApiClient>().post('/chat', {
        'message': text,
        if (_contextLr != null) 'context_lr_number': _contextLr,
      }) as Map<String, dynamic>;
      if (!mounted) return;
      final lrNumbers = (reply['lr_numbers'] as List).cast<String>();
      setState(() {
        _messages.add(_Message(reply['answer'] as String, mine: false, lrNumbers: lrNumbers));
        _suggestions = (reply['suggestions'] as List).cast<String>();
        if (lrNumbers.length == 1) _contextLr = lrNumbers.single;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _messages.add(_Message(e.message, mine: false, failed: true)));
    } finally {
      if (mounted) setState(() => _waiting = false);
      _scrollToEnd();
    }
  }

  Widget _bubble(_Message message) {
    final text = Theme.of(context).textTheme;
    final color = message.failed
        ? Palette.errorContainer
        : message.mine
            ? Palette.primary
            : Palette.surface;
    return Align(
      alignment: message.mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.84),
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(18),
            topRight: const Radius.circular(18),
            bottomLeft: Radius.circular(message.mine ? 18 : 4),
            bottomRight: Radius.circular(message.mine ? 4 : 18),
          ),
          border: message.mine || message.failed ? null : Border.all(color: Palette.outline),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SelectableText(
              message.text,
              style: text.bodyLarge!.copyWith(
                color: message.mine
                    ? Palette.onPrimary
                    : message.failed
                        ? Palette.error
                        : Palette.onSurface,
              ),
            ),
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

  Widget _welcome() {
    final text = Theme.of(context).textTheme;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 32, 16, 16),
      children: [
        Container(
          width: 56,
          height: 56,
          alignment: Alignment.centerLeft,
          child: Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(color: Palette.primaryContainer, borderRadius: BorderRadius.circular(16)),
            child: const Icon(Icons.chat_bubble_outline, color: Palette.onPrimaryContainer),
          ),
        ),
        const SizedBox(height: 16),
        Text('Ask about your goods', style: text.headlineMedium),
        const SizedBox(height: 8),
        Text(
          'Try an LR number, a city, a day, or a truck number. I look things up; I never change anything.',
          style: text.bodyLarge!.copyWith(color: Palette.onSurfaceVariant),
        ),
      ],
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
                  ? _welcome()
                  : ListView(
                      controller: _scroll,
                      padding: const EdgeInsets.all(16),
                      children: [
                        for (final m in _messages) _bubble(m),
                        if (_waiting) _bubble(const _Message('Looking that up…', mine: false)),
                      ],
                    ),
            ),
            if (_suggestions.isNotEmpty && !_waiting)
              SizedBox(
                height: 44,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  itemCount: _suggestions.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, i) => ActionChip(
                    label: Text(_suggestions[i]),
                    labelStyle: text.labelMedium!.copyWith(color: Palette.link),
                    backgroundColor: Palette.surface,
                    side: const BorderSide(color: Palette.outline),
                    shape: const StadiumBorder(),
                    onPressed: () => _send(_suggestions[i]),
                  ),
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
                      decoration: const InputDecoration(hintText: 'Ask about an LR, a city or a truck'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    tooltip: 'Send',
                    onPressed: _waiting ? null : () => _send(_input.text),
                    icon: const Icon(Icons.arrow_upward),
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
