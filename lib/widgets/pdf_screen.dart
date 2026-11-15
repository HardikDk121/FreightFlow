import 'package:flutter/material.dart';
import 'package:pdf/pdf.dart';
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';

/// Shows an A4 PDF from the server with print, share and save. Used for reports and load sheets.
class PdfScreen extends StatelessWidget {
  const PdfScreen({super.key, required this.title, required this.path, required this.fileName});

  final String title;

  /// API path that returns the PDF, including any query string.
  final String path;
  final String fileName;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(title)),
        body: PdfPreview(
          build: (_) => context.read<ApiClient>().getBytes(path),
          initialPageFormat: PdfPageFormat.a4,
          canChangePageFormat: false,
          canChangeOrientation: false,
          canDebug: false,
          pdfFileName: fileName,
        ),
      );
}
