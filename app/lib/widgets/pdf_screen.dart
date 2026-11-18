import 'package:flutter/material.dart';
import 'package:pdf/pdf.dart';
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';

/// Shows a PDF from the server with print, share and save. A4 unless [pageFormat] says otherwise.
class PdfScreen extends StatelessWidget {
  const PdfScreen({
    super.key,
    required this.title,
    required this.path,
    required this.fileName,
    this.pageFormat = PdfPageFormat.a4,
  });

  final String title;

  /// API path that returns the PDF, including any query string.
  final String path;
  final String fileName;
  final PdfPageFormat pageFormat;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(title)),
        body: PdfPreview(
          build: (_) => context.read<ApiClient>().getBytes(path),
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
