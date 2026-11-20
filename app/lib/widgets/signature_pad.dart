import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// A box to sign in with a finger. Reports the strokes drawn so far after each one.
class SignaturePad extends StatefulWidget {
  const SignaturePad({super.key, required this.onChanged});

  final ValueChanged<List<List<Offset>>> onChanged;

  @override
  State<SignaturePad> createState() => _SignaturePadState();
}

class _SignaturePadState extends State<SignaturePad> {
  final List<List<Offset>> _strokes = [];

  void _start(Offset point) => setState(() => _strokes.add([point]));

  void _extend(Offset point) => setState(() => _strokes.last.add(point));

  void _finish() => widget.onChanged([for (final stroke in _strokes) List.of(stroke)]);

  void _clear() {
    setState(_strokes.clear);
    widget.onChanged(const []);
  }

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Container(
            height: 180,
            decoration: BoxDecoration(
              color: Palette.surface,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Palette.outline),
            ),
            clipBehavior: Clip.antiAlias,
            // Both drag directions are claimed here, so signing does not scroll the page.
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onVerticalDragStart: (d) => _start(d.localPosition),
              onVerticalDragUpdate: (d) => _extend(d.localPosition),
              onVerticalDragEnd: (_) => _finish(),
              onHorizontalDragStart: (d) => _start(d.localPosition),
              onHorizontalDragUpdate: (d) => _extend(d.localPosition),
              onHorizontalDragEnd: (_) => _finish(),
              child: CustomPaint(painter: _SignaturePainter(_strokes), size: Size.infinite),
            ),
          ),
          TextButton(onPressed: _strokes.isEmpty ? null : _clear, child: const Text('Clear')),
        ],
      );
}

class _SignaturePainter extends CustomPainter {
  _SignaturePainter(this.strokes);

  final List<List<Offset>> strokes;

  @override
  void paint(Canvas canvas, Size size) {
    final pen = Paint()
      ..color = Palette.onSurface
      ..strokeWidth = 2.5
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;
    for (final stroke in strokes) {
      for (var i = 1; i < stroke.length; i++) {
        canvas.drawLine(stroke[i - 1], stroke[i], pen);
      }
    }
  }

  // The list is mutated in place as the finger moves, so always repaint.
  @override
  bool shouldRepaint(_SignaturePainter oldDelegate) => true;
}
