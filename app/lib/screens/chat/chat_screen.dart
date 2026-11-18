import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../theme/app_theme.dart';
import '../../widgets/common.dart';
import '../shell.dart';

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
    if (message.mine) {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.only(bottom: 12, left: 48),
          padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
          decoration: BoxDecoration(color: Palette.ink, borderRadius: BorderRadius.circular(22)),
          child: SelectableText(message.text, style: onInk(text.bodyMedium!)),
        ),
      );
    }
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12, right: 32),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: message.failed ? Palette.errorContainer : Palette.surface,
          borderRadius: BorderRadius.circular(22),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                color: message.failed ? Palette.error : Palette.primary,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(
                message.failed ? Icons.error_outline : Icons.auto_awesome,
                size: 18,
                color: message.failed ? Palette.onInk : Palette.onPrimary,
              ),
            ),
            const SizedBox(height: 10),
            SelectableText(
              message.text,
              style: text.bodyMedium!.copyWith(color: message.failed ? Palette.error : Palette.onSurface),
            ),
            if (message.lrNumbers.isNotEmpty) ...[
              const SizedBox(height: 10),
              StatusChip.tone(
                'From ${message.lrNumbers.length == 1 ? message.lrNumbers.single : '${message.lrNumbers.length} LRs'}',
                Tone.success,
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
      padding: const EdgeInsets.fromLTRB(20, 28, 20, 16),
      children: [
        Text('Your goods.\nOne conversation.', style: text.displaySmall),
        const SizedBox(height: 12),
        Text(
          'Ask about an LR, a city, a day or a truck. I look things up; I never change anything.',
          style: text.bodyMedium!.copyWith(color: Palette.onSurfaceMuted),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      body: Column(
        children: [
          HeroHeader(
            leading: Row(
              children: [
                const Icon(Icons.auto_awesome, color: Palette.primary),
                const SizedBox(width: 10),
                Text('Ask FreightFlow', style: onInk(text.titleLarge!)),
              ],
            ),
            title: '',
            child: Row(
              children: [
                StatusChip.tone('Read only', Tone.dark),
                const SizedBox(width: 10),
                Expanded(
                  child: Text('Answers, without changing a thing.', style: onInk(text.bodySmall!, muted: true)),
                ),
              ],
            ),
          ),
          Expanded(
            child: _messages.isEmpty
                ? _welcome()
                : ListView(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(20, 20, 20, 12),
                    children: [
                      for (final m in _messages) _bubble(m),
                      if (_waiting) _bubble(const _Message('Looking that up…', mine: false)),
                    ],
                  ),
          ),
          if (_suggestions.isNotEmpty && !_waiting)
            SizedBox(
              height: 46,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 20),
                itemCount: _suggestions.length,
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (_, i) => ActionChip(
                  label: Text(_suggestions[i]),
                  labelStyle: text.labelMedium,
                  backgroundColor: Palette.surface,
                  side: BorderSide.none,
                  shape: const StadiumBorder(),
                  onPressed: () => _send(_suggestions[i]),
                ),
              ),
            ),
          Padding(
            // Clears the floating navigation bar, which this screen sits under.
            padding: const EdgeInsets.fromLTRB(20, 10, 20, navBarClearance - 18),
            child: Container(
              padding: const EdgeInsets.only(left: 18, right: 6),
              decoration: BoxDecoration(color: Palette.surface, borderRadius: BorderRadius.circular(999)),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _input,
                      textInputAction: TextInputAction.send,
                      onSubmitted: _send,
                      decoration: const InputDecoration(
                        hintText: 'Ask about your goods…',
                        filled: false,
                        border: InputBorder.none,
                        enabledBorder: InputBorder.none,
                        focusedBorder: InputBorder.none,
                        contentPadding: EdgeInsets.symmetric(vertical: 16),
                      ),
                    ),
                  ),
                  IconButton.filled(
                    tooltip: 'Send',
                    style: IconButton.styleFrom(
                      backgroundColor: Palette.primary,
                      foregroundColor: Palette.onPrimary,
                      minimumSize: const Size(46, 46),
                    ),
                    onPressed: _waiting ? null : () => _send(_input.text),
                    icon: const Icon(Icons.arrow_upward),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
