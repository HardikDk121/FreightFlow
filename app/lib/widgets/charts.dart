import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'common.dart';

/// One bar or point in a chart.
class ChartPoint {
  const ChartPoint(this.label, this.value, {this.secondary});

  final String label;
  final double value;

  /// An optional second series drawn as a line over the bars (for example, collections over revenue).
  final double? secondary;
}

/// Bars with an optional line over them. Tap a bar to read its exact figures. No package needed.
class BarLineChart extends StatefulWidget {
  const BarLineChart({
    super.key,
    required this.points,
    required this.format,
    this.height = 180,
    this.barLegend,
    this.lineLegend,
  });

  final List<ChartPoint> points;
  final String Function(double value) format;
  final double height;
  final String? barLegend;
  final String? lineLegend;

  @override
  State<BarLineChart> createState() => _BarLineChartState();
}

class _BarLineChartState extends State<BarLineChart> {
  int? _selected;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final points = widget.points;
    if (points.isEmpty) return const SizedBox.shrink();
    final selected = _selected == null || _selected! >= points.length ? null : points[_selected!];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          height: 34,
          child: selected == null
              ? Text(
                  [
                    if (widget.barLegend != null) '▮ ${widget.barLegend}',
                    if (widget.lineLegend != null) '— ${widget.lineLegend}',
                    'Tap a bar for its figures',
                  ].join('   '),
                  style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted),
                )
              : Text(
                  '${selected.label}: ${widget.format(selected.value)}'
                  '${selected.secondary != null && widget.lineLegend != null ? ' · ${widget.lineLegend} ${widget.format(selected.secondary!)}' : ''}',
                  style: text.labelLarge,
                ),
        ),
        LayoutBuilder(
          builder: (context, box) => GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapDown: (d) {
              final index = (d.localPosition.dx / box.maxWidth * points.length).floor().clamp(0, points.length - 1);
              setState(() => _selected = _selected == index ? null : index);
            },
            child: CustomPaint(
              size: Size(box.maxWidth, widget.height),
              painter: _BarLinePainter(points, _selected),
            ),
          ),
        ),
        const SizedBox(height: 6),
        Row(
          children: [
            Text(points.first.label, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
            const Spacer(),
            if (points.length > 1) Text(points.last.label, style: text.bodySmall!.copyWith(color: Palette.onSurfaceMuted)),
          ],
        ),
      ],
    );
  }
}

class _BarLinePainter extends CustomPainter {
  _BarLinePainter(this.points, this.selected);

  final List<ChartPoint> points;
  final int? selected;

  @override
  void paint(Canvas canvas, Size size) {
    final top = points.fold<double>(0, (m, p) => [m, p.value, p.secondary ?? 0].reduce((a, b) => a > b ? a : b));
    if (top <= 0) {
      canvas.drawLine(Offset(0, size.height - 1), Offset(size.width, size.height - 1), Paint()..color = Palette.outline);
      return;
    }
    final slot = size.width / points.length;
    final gap = slot > 8 ? slot * 0.2 : 1.0;
    final radius = Radius.circular((slot - gap) / 2 > 6 ? 6 : (slot - gap) / 2);
    for (var i = 0; i < points.length; i++) {
      final h = points[i].value / top * (size.height - 4);
      final rect = RRect.fromRectAndCorners(
        Rect.fromLTWH(i * slot + gap / 2, size.height - h, slot - gap, h),
        topLeft: radius,
        topRight: radius,
      );
      canvas.drawRRect(rect, Paint()..color = i == selected ? Palette.ink : Palette.primary);
    }
    final line = [
      for (var i = 0; i < points.length; i++)
        if (points[i].secondary != null) Offset(i * slot + slot / 2, size.height - points[i].secondary! / top * (size.height - 4)),
    ];
    if (line.length > 1) {
      final path = Path()..moveTo(line.first.dx, line.first.dy);
      for (final p in line.skip(1)) {
        path.lineTo(p.dx, p.dy);
      }
      canvas.drawPath(path, Paint()
        ..color = Palette.success
        ..strokeWidth = 2.5
        ..style = PaintingStyle.stroke);
    }
    canvas.drawLine(Offset(0, size.height), Offset(size.width, size.height), Paint()..color = Palette.outline);
  }

  @override
  bool shouldRepaint(_BarLinePainter old) => old.points != points || old.selected != selected;
}

/// A table that scrolls sideways when wide, with aligned figures. Tapping a row calls [onTap].
class DataGrid extends StatelessWidget {
  const DataGrid({super.key, required this.columns, required this.rows, this.onTap});

  final List<String> columns;
  final List<List<String>> rows;
  final void Function(int row)? onTap;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return AppCard(
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          headingTextStyle: text.labelMedium,
          dataTextStyle: text.bodyMedium,
          headingRowHeight: 44,
          dataRowMinHeight: 44,
          columnSpacing: 22,
          showCheckboxColumn: false,
          columns: [for (final c in columns) DataColumn(label: Text(c))],
          rows: [
            for (var i = 0; i < rows.length; i++)
              DataRow(
                onSelectChanged: onTap == null ? null : (_) => onTap!(i),
                cells: [for (final cell in rows[i]) DataCell(Text(cell))],
              ),
          ],
        ),
      ),
    );
  }
}
