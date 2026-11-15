import 'package:pdf/pdf.dart';

/// Matches the page size in the server's lr_template.json.
final lrPageFormat = PdfPageFormat(210 * PdfPageFormat.mm, 148 * PdfPageFormat.mm);

/// "2026-10-04" -> "04-10-2026", the way the LR prints dates.
String lrDateLabel(String isoDate) {
  final parts = isoDate.split('-');
  return '${parts[2]}-${parts[1]}-${parts[0]}';
}
