import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:pdf/pdf.dart';
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';

/// Shows a PDF with print, share and save: fetched from [path], or [bytes] already fetched (for
/// PDFs that come from a POST). A4 unless [pageFormat] says otherwise.
class PdfScreen extends StatelessWidget {
  const PdfScreen({
    super.key,
    required this.title,
    this.path,
    this.bytes,
    required this.fileName,
    this.pageFormat = PdfPageFormat.a4,
  }) : assert((path == null) != (bytes == null), 'Give a path or the bytes, not both.');

  final String title;

  /// API path that returns the PDF, including any query string.
  final String? path;
  final Uint8List? bytes;
  final String fileName;
  final PdfPageFormat pageFormat;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(title)),
        body: PdfPreview(
          build: (_) async => bytes ?? await context.read<ApiClient>().getBytes(path!),
          initialPageFormat: pageFormat,
          canChangePageFormat: false,
          canChangeOrientation: false,
          canDebug: false,
          pdfFileName: fileName,
          scrollViewDecoration: const BoxDecoration(color: Palette.background),
          pdfPreviewPageDecoration: const BoxDecoration(color: Colors.white),
        ),
      );
}
