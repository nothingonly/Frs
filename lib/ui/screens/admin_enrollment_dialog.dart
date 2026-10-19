import 'dart:typed_data';
import 'package:flutter/material.dart';

import '../../config/app_config.dart';
import '../../exceptions/api_exceptions.dart';
import '../../services/api_service.dart';
import '../theme/app_theme.dart';
import '../widgets/camera_viewport.dart';

/// Administrative dialog for enrolling new employees and capturing reference face templates.
class AdminEnrollmentDialog extends StatefulWidget {
  final AppConfig config;
  final FrsApiService apiService;

  const AdminEnrollmentDialog({
    super.key,
    required this.config,
    required this.apiService,
  });

  @override
  State<AdminEnrollmentDialog> createState() => _AdminEnrollmentDialogState();
}

class _AdminEnrollmentDialogState extends State<AdminEnrollmentDialog> {
  final _formKey = GlobalKey<FormState>();
  final _employeeIdController = TextEditingController();
  final _nameController = TextEditingController();
  final _departmentController = TextEditingController();

  Uint8List? _capturedImage;
  bool _isSubmitting = false;
  String? _successMessage;
  String? _errorMessage;
  Map<String, dynamic>? _qualityMetrics;

  @override
  void dispose() {
    _employeeIdController.dispose();
    _nameController.dispose();
    _departmentController.dispose();
    super.dispose();
  }

  Future<void> _submitEnrollment() async {
    if (!_formKey.currentState!.validate()) return;
    if (_capturedImage == null || _capturedImage!.isEmpty) {
      setState(() {
        _errorMessage = 'Please capture a facial photo before enrolling.';
      });
      return;
    }

    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
      _successMessage = null;
    });

    try {
      final res = await widget.apiService.adminEnroll(
        employeeId: _employeeIdController.text.trim(),
        fullName: _nameController.text.trim(),
        department: _departmentController.text.trim().isEmpty ? null : _departmentController.text.trim(),
        imageBytes: _capturedImage!,
      );

      setState(() {
        _isSubmitting = false;
        _successMessage = 'Employee ${_employeeIdController.text.trim()} enrolled successfully!';
        _qualityMetrics = res['quality_metrics'] as Map<String, dynamic>?;
      });
    } on FrsApiException catch (e) {
      setState(() {
        _isSubmitting = false;
        _errorMessage = e.message;
      });
    } catch (e) {
      setState(() {
        _isSubmitting = false;
        _errorMessage = 'Enrollment failed: $e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 500, maxHeight: 720),
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: SingleChildScrollView(
            child: Form(
              key: _formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.admin_panel_settings, color: AppTheme.primaryBlue, size: 28),
                      const SizedBox(width: 12),
                      const Expanded(
                        child: Text(
                          'Administrator Enrollment',
                          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close),
                        onPressed: () => Navigator.of(context).pop(),
                      ),
                    ],
                  ),
                  const Divider(height: 24),

                  // Camera capture preview
                  SizedBox(
                    height: 260,
                    child: CameraViewport(
                      capturedImage: _capturedImage,
                      onImageCaptured: (bytes) => setState(() => _capturedImage = bytes),
                      onRetakePressed: () => setState(() => _capturedImage = null),
                      isSubmitting: _isSubmitting,
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Employee Details Form
                  TextFormField(
                    controller: _employeeIdController,
                    decoration: const InputDecoration(
                      labelText: 'Employee ID / Roll Number *',
                      prefixIcon: Icon(Icons.badge_outlined),
                      border: OutlineInputBorder(),
                    ),
                    validator: (v) => v == null || v.trim().isEmpty ? 'Employee ID is required' : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _nameController,
                    decoration: const InputDecoration(
                      labelText: 'Full Name *',
                      prefixIcon: Icon(Icons.person_outline),
                      border: OutlineInputBorder(),
                    ),
                    validator: (v) => v == null || v.trim().isEmpty ? 'Full name is required' : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _departmentController,
                    decoration: const InputDecoration(
                      labelText: 'Department (Optional)',
                      prefixIcon: Icon(Icons.business_outlined),
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 16),

                  // Feedback Cards
                  if (_successMessage != null) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: AppTheme.successBg,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: AppTheme.successGreen.withOpacity(0.5)),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              const Icon(Icons.check_circle, color: AppTheme.successGreen, size: 20),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  _successMessage!,
                                  style: const TextStyle(
                                    color: AppTheme.successGreen,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                            ],
                          ),
                          if (_qualityMetrics != null) ...[
                            const SizedBox(height: 6),
                            Text(
                              'Sharpness: ${_qualityMetrics!['sharpness']} | Luminance: ${_qualityMetrics!['luminance']}',
                              style: const TextStyle(fontSize: 12, color: AppTheme.textSecondary),
                            ),
                          ],
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                  ],

                  if (_errorMessage != null) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: AppTheme.errorBg,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: AppTheme.errorRed.withOpacity(0.5)),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.error_outline, color: AppTheme.errorRed, size: 20),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              _errorMessage!,
                              style: const TextStyle(color: AppTheme.errorRed),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                  ],

                  // Action Button
                  ElevatedButton.icon(
                    onPressed: _isSubmitting ? null : _submitEnrollment,
                    icon: _isSubmitting
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : const Icon(Icons.save_rounded),
                    label: Text(_isSubmitting ? 'Enrolling Biometrics...' : 'Enroll Employee'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.primaryBlue,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
