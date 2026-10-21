import 'dart:io';
import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Camera Viewport managing physical camera hardware, lens selection,
/// rear/front switching, and single/burst frame capture for group attendance.
class CameraViewport extends StatefulWidget {
  final List<Uint8List>? capturedImages;
  final ValueChanged<List<Uint8List>>? onImagesCaptured;
  final ValueChanged<Uint8List>? onSingleImageCaptured;
  final VoidCallback onRetakePressed;
  final bool isSubmitting;
  final bool isActive;
  final bool canRetake;
  final bool isGroupMode;
  final String? captureButtonLabel;
  final String? statusMessage;
  final bool allowCameraSwitch;
  final CameraLensDirection? initialLensDirection;

  const CameraViewport({
    super.key,
    required this.capturedImages,
    this.onImagesCaptured,
    this.onSingleImageCaptured,
    required this.onRetakePressed,
    this.isSubmitting = false,
    this.isActive = true,
    this.canRetake = true,
    this.isGroupMode = true,
    this.captureButtonLabel,
    this.statusMessage,
    this.allowCameraSwitch = true,
    this.initialLensDirection,
  });

  @override
  State<CameraViewport> createState() => CameraViewportState();
}

class CameraViewportState extends State<CameraViewport> with WidgetsBindingObserver {
  CameraController? _controller;
  List<CameraDescription> _availableCameras = [];
  int? _currentCameraIndex;
  bool _isInitialized = false;
  bool _isPermissionDenied = false;
  bool _isCapturing = false;
  String? _errorMessage;

  Uint8List? get _previewImage {
    final frames = widget.capturedImages;
    return frames != null && frames.isNotEmpty ? frames.first : null;
  }

  static const int _burstFrameCount = 3;

  CameraDescription? get currentCamera {
    if (_availableCameras.isEmpty || _currentCameraIndex == null) return null;
    if (_currentCameraIndex! >= 0 && _currentCameraIndex! < _availableCameras.length) {
      return _availableCameras[_currentCameraIndex!];
    }
    return null;
  }

  bool get isRearCamera => currentCamera?.lensDirection == CameraLensDirection.back;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (widget.isActive) _initializeCamera();
  }

  @override
  void didUpdateWidget(covariant CameraViewport oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.isActive == widget.isActive) return;
    if (widget.isActive) {
      _resumeCamera();
    } else {
      _pauseCamera();
    }
  }

  /// Public pause hook so a parent can wait for hardware release before opening
  /// another camera-consuming route.
  Future<void> pauseCamera() => _pauseCamera();

  Future<void> _pauseCamera() async {
    await _disposeController();
    if (mounted) {
      setState(() {
        _isInitialized = false;
        _isCapturing = false;
      });
    }
  }

  Future<void> _resumeCamera() async {
    await _disposeController();
    if (mounted && widget.isActive) await _initializeCamera();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _disposeController();
    super.dispose();
  }

  Future<void> _disposeController() async {
    final c = _controller;
    _controller = null;
    if (c != null) {
      await c.dispose();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final CameraController? cameraController = _controller;
    if (!widget.isActive || cameraController == null || !cameraController.value.isInitialized) {
      return;
    }

    if (state == AppLifecycleState.inactive || state == AppLifecycleState.paused) {
      _disposeController();
      if (mounted) {
        setState(() {
          _isInitialized = false;
        });
      }
    } else if (state == AppLifecycleState.resumed) {
      _resumeCamera();
    }
  }

  Future<void> _initializeCamera() async {
    if (!mounted || !widget.isActive) return;
    setState(() {
      _errorMessage = null;
      _isPermissionDenied = false;
    });

    try {
      _availableCameras = await availableCameras();
      if (!mounted || !widget.isActive) return;
      if (_availableCameras.isEmpty) {
        if (!mounted) return;
        setState(() {
          _isInitialized = false;
          _errorMessage = 'No camera hardware found on this device.';
        });
        return;
      }

      // Determine initial lens direction:
      // Group attendance mode defaults to REAR camera (facing students in classroom).
      // Individual enrollment mode defaults to FRONT camera.
      if (_currentCameraIndex == null) {
        final targetDirection = widget.initialLensDirection ??
            (widget.isGroupMode ? CameraLensDirection.back : CameraLensDirection.front);

        final matchedIndex = _availableCameras.indexWhere((c) => c.lensDirection == targetDirection);
        if (matchedIndex != -1) {
          _currentCameraIndex = matchedIndex;
        } else {
          _currentCameraIndex = 0;
        }
      }

      final camera = _availableCameras[_currentCameraIndex!];

      final controller = CameraController(
        camera,
        // High resolution provides superior detection for small/distant faces in classrooms.
        widget.isGroupMode ? ResolutionPreset.high : ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.jpeg,
      );

      _controller = controller;
      await controller.initialize();

      if (!mounted || !widget.isActive) {
        await controller.dispose();
        if (identical(_controller, controller)) _controller = null;
        return;
      }
      setState(() {
        _isInitialized = true;
        _isPermissionDenied = false;
        _errorMessage = null;
      });
    } on CameraException catch (e) {
      if (!mounted || !widget.isActive) return;
      setState(() {
        _isInitialized = false;
        if (e.code == 'CameraAccessDenied' || e.code == 'CameraAccessDeniedWithoutPrompt') {
          _isPermissionDenied = true;
          _errorMessage = 'Camera permission denied. Please grant camera access in Android system settings.';
        } else {
          _errorMessage = 'Camera hardware error (${e.code}): ${e.description ?? ""}';
        }
      });
    } catch (e) {
      if (!mounted || !widget.isActive) return;
      setState(() {
        _isInitialized = false;
        _errorMessage = 'Failed to initialize camera: $e';
      });
    }
  }

  Future<void> _switchCamera() async {
    if (_availableCameras.length < 2 || _isCapturing || widget.isSubmitting) return;
    final nextIndex = ((_currentCameraIndex ?? 0) + 1) % _availableCameras.length;
    setState(() {
      _currentCameraIndex = nextIndex;
      _isInitialized = false;
    });
    await _disposeController();
    await _initializeCamera();
  }

  Future<void> _handleCapture() async {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) return;
    if (_isCapturing || widget.isSubmitting) return;

    setState(() => _isCapturing = true);

    try {
      // 1. Single group photo capture mode
      if (widget.onSingleImageCaptured != null) {
        final XFile photo = await controller.takePicture();
        try {
          final bytes = await photo.readAsBytes();
          if (bytes.isEmpty) throw StateError('Camera produced an empty image frame.');
          if (mounted) {
            widget.onSingleImageCaptured!(bytes);
          }
        } finally {
          try {
            await File(photo.path).delete();
          } catch (_) {}
        }
      }
      // 2. Burst capture mode (for legacy single-person kiosk identification)
      else if (widget.onImagesCaptured != null) {
        final capturedFrames = <Uint8List>[];
        for (var frameIndex = 0; frameIndex < _burstFrameCount; frameIndex++) {
          if (frameIndex > 0) {
            await Future<void>.delayed(const Duration(milliseconds: 220));
          }
          if (!controller.value.isInitialized) {
            throw StateError('Camera became unavailable during the capture burst.');
          }
          final XFile photo = await controller.takePicture();
          try {
            final bytes = await photo.readAsBytes();
            if (bytes.isEmpty) throw StateError('Camera produced an empty frame.');
            capturedFrames.add(bytes);
          } finally {
            try {
              await File(photo.path).delete();
            } catch (_) {}
          }
        }
        if (capturedFrames.length != _burstFrameCount) {
          throw StateError('The full $_burstFrameCount-frame capture burst was not completed.');
        }
        if (mounted) {
          widget.onImagesCaptured!(List<Uint8List>.unmodifiable(capturedFrames));
        }
      }
    } on CameraException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTheme.errorRed,
            content: Text('Camera capture failed: ${e.description ?? e.code}'),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTheme.errorRed,
            content: Text('Capture failed: $e'),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isCapturing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final lensLabel = isRearCamera ? 'Rear Camera' : 'Front Camera';
    final defaultGuidance = widget.isGroupMode
        ? 'Frame Class Rows — Ensure All Faces Visible'
        : 'Align Face Inside Oval Reticle';

    final effectiveGuidance = widget.statusMessage ??
        (_previewImage != null
            ? '${widget.capturedImages?.length ?? 1} Image Captured — Ready for Verification'
            : (_isInitialized ? defaultGuidance : 'Camera Hardware Status'));

    final defaultButtonLabel = widget.isGroupMode ? 'Capture Group Photo' : 'Capture Face';
    final buttonLabel = widget.captureButtonLabel ?? defaultButtonLabel;

    return Container(
      decoration: BoxDecoration(
        color: AppTheme.primaryDark,
        borderRadius: BorderRadius.circular(20),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.12),
            blurRadius: 16,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: Stack(
        alignment: Alignment.center,
        children: [
          // 1. Live camera preview OR captured photo OR error view
          if (_previewImage != null)
            Image.memory(
              _previewImage!,
              fit: BoxFit.cover,
              width: double.infinity,
              height: double.infinity,
            )
          else if (_isInitialized && _controller != null)
            SizedBox.expand(
              child: FittedBox(
                fit: BoxFit.cover,
                child: SizedBox(
                  width: _controller!.value.previewSize?.height ?? 1,
                  height: _controller!.value.previewSize?.width ?? 1,
                  child: CameraPreview(_controller!),
                ),
              ),
            )
          else
            _buildStatusPlaceholder(),

          // 2. Framing Guide Overlay
          // Classroom wide-view framing guide for group photos, or oval reticle for single enrollment
          IgnorePointer(
            child: CustomPaint(
              size: Size.infinite,
              painter: widget.isGroupMode ? _GroupFramingGuidePainter() : _FaceReticlePainter(),
            ),
          ),

          // 3. Top Controls Bar: Lens indicator, Guidance banner, and Camera switcher
          Positioned(
            top: 16,
            left: 16,
            right: 16,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                // Active Lens Badge
                if (_isInitialized)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(0.65),
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: Colors.white.withOpacity(0.2)),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          isRearCamera ? Icons.camera_rear_rounded : Icons.camera_front_rounded,
                          color: AppTheme.primaryBlue,
                          size: 14,
                        ),
                        const SizedBox(width: 5),
                        Text(
                          lensLabel,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  )
                else
                  const SizedBox.shrink(),

                // Center Guidance Banner
                Flexible(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                    decoration: BoxDecoration(
                      color: Colors.black.withOpacity(0.7),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: Colors.white.withOpacity(0.25)),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          _previewImage != null
                              ? Icons.check_circle_outline
                              : (_isInitialized ? Icons.groups_rounded : Icons.camera_alt_outlined),
                          color: _previewImage != null ? AppTheme.successGreen : Colors.white,
                          size: 16,
                        ),
                        const SizedBox(width: 6),
                        Flexible(
                          child: Text(
                            effectiveGuidance,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),

                // Camera Switcher Button (Flip Camera)
                if (widget.allowCameraSwitch && _availableCameras.length > 1 && _previewImage == null)
                  Material(
                    color: Colors.black.withOpacity(0.65),
                    borderRadius: BorderRadius.circular(20),
                    child: InkWell(
                      key: const ValueKey('switch_camera_button'),
                      onTap: (_isCapturing || widget.isSubmitting) ? null : _switchCamera,
                      borderRadius: BorderRadius.circular(20),
                      child: Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(20),
                          border: Border.all(color: Colors.white.withOpacity(0.2)),
                        ),
                        child: const Icon(
                          Icons.flip_camera_ios_rounded,
                          color: Colors.white,
                          size: 18,
                        ),
                      ),
                    ),
                  )
                else
                  const SizedBox.shrink(),
              ],
            ),
          ),

          // 4. Capture & Retake Controls at bottom
          Positioned(
            bottom: 24,
            left: 0,
            right: 0,
            child: Center(
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (_previewImage != null)
                    ElevatedButton.icon(
                      onPressed: (widget.isSubmitting || !widget.canRetake) ? null : widget.onRetakePressed,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.white.withOpacity(0.9),
                        foregroundColor: AppTheme.primaryDark,
                        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
                        minimumSize: Size.zero,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(30)),
                      ),
                      icon: const Icon(Icons.refresh_rounded, size: 20),
                      label: const Text('Retake / Clear Frame'),
                    )
                  else if (_isInitialized)
                    ElevatedButton.icon(
                      key: const ValueKey('capture_camera_button'),
                      onPressed: (_isCapturing || widget.isSubmitting) ? null : _handleCapture,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.primaryBlue,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
                        minimumSize: Size.zero,
                        elevation: 4,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(30),
                        ),
                      ),
                      icon: _isCapturing
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : const Icon(Icons.camera_alt_rounded, size: 22),
                      label: Text(
                        _isCapturing ? 'Processing Capture...' : buttonLabel,
                        style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                      ),
                    )
                  else
                    ElevatedButton.icon(
                      onPressed: _initializeCamera,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.white.withOpacity(0.2),
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                        minimumSize: Size.zero,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                      ),
                      icon: const Icon(Icons.refresh_rounded, size: 18),
                      label: const Text('Retry Camera'),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusPlaceholder() {
    return Container(
      color: const Color(0xFF1E293B),
      padding: const EdgeInsets.all(24),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              _isPermissionDenied ? Icons.no_photography_rounded : Icons.videocam_off_rounded,
              size: 56,
              color: _isPermissionDenied ? AppTheme.errorRed : Colors.white.withOpacity(0.4),
            ),
            const SizedBox(height: 12),
            Text(
              _isPermissionDenied
                  ? 'Camera Permission Denied'
                  : (_errorMessage ?? 'Initializing Camera Hardware...'),
              textAlign: TextAlign.center,
              style: TextStyle(
                color: _isPermissionDenied ? AppTheme.errorRed : Colors.white.withOpacity(0.8),
                fontSize: 15,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              _isPermissionDenied
                  ? 'Grant CAMERA permission in device Settings to enable classroom attendance.'
                  : 'Probing camera sensors (rear camera default)...',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white.withOpacity(0.5),
                fontSize: 12,
              ),
            ),
            if (_isPermissionDenied || _errorMessage != null) ...[
              const SizedBox(height: 16),
              ElevatedButton.icon(
                key: const ValueKey('retry_camera_button'),
                onPressed: _initializeCamera,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppTheme.primaryBlue,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: const Text('Retry Camera Access'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Classroom framing guide for group photos: renders corner brackets and rule-of-thirds
/// guides to help faculty capture crisp rows of students in lecture halls and laboratories.
class _GroupFramingGuidePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final marginX = size.width * 0.06;
    final marginY = size.height * 0.12;
    final rect = Rect.fromLTRB(marginX, marginY, size.width - marginX, size.height - marginY);

    // Subtle rule-of-thirds grid
    final gridPaint = Paint()
      ..color = Colors.white.withOpacity(0.12)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    final stepX = rect.width / 3.0;
    final stepY = rect.height / 3.0;

    // Vertical grid lines
    canvas.drawLine(Offset(rect.left + stepX, rect.top), Offset(rect.left + stepX, rect.bottom), gridPaint);
    canvas.drawLine(Offset(rect.left + 2 * stepX, rect.top), Offset(rect.left + 2 * stepX, rect.bottom), gridPaint);

    // Horizontal grid lines
    canvas.drawLine(Offset(rect.left, rect.top + stepY), Offset(rect.right, rect.top + stepY), gridPaint);
    canvas.drawLine(Offset(rect.left, rect.top + 2 * stepY), Offset(rect.right, rect.top + 2 * stepY), gridPaint);

    // Corner brackets
    final bracketPaint = Paint()
      ..color = AppTheme.primaryBlue
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3.5
      ..strokeCap = StrokeCap.round;

    const cornerLen = 28.0;

    // Top-Left
    canvas.drawLine(Offset(rect.left, rect.top + cornerLen), Offset(rect.left, rect.top), bracketPaint);
    canvas.drawLine(Offset(rect.left, rect.top), Offset(rect.left + cornerLen, rect.top), bracketPaint);

    // Top-Right
    canvas.drawLine(Offset(rect.right - cornerLen, rect.top), Offset(rect.right, rect.top), bracketPaint);
    canvas.drawLine(Offset(rect.right, rect.top), Offset(rect.right, rect.top + cornerLen), bracketPaint);

    // Bottom-Left
    canvas.drawLine(Offset(rect.left, rect.bottom - cornerLen), Offset(rect.left, rect.bottom), bracketPaint);
    canvas.drawLine(Offset(rect.left, rect.bottom), Offset(rect.left + cornerLen, rect.bottom), bracketPaint);

    // Bottom-Right
    canvas.drawLine(Offset(rect.right - cornerLen, rect.bottom), Offset(rect.right, rect.bottom), bracketPaint);
    canvas.drawLine(Offset(rect.right, rect.bottom), Offset(rect.right, rect.bottom - cornerLen), bracketPaint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// Custom painter rendering a dashed/solid oval biometric alignment guide for individual enrollment.
class _FaceReticlePainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height * 0.44);
    final ovalWidth = size.width * 0.55;
    final ovalHeight = size.height * 0.50;
    final rect = Rect.fromCenter(center: center, width: ovalWidth, height: ovalHeight);

    final paint = Paint()
      ..color = Colors.white.withOpacity(0.7)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.5;

    canvas.drawOval(rect, paint);

    final cornerPaint = Paint()
      ..color = AppTheme.primaryBlue
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4.0
      ..strokeCap = StrokeCap.round;

    final halfH = ovalHeight / 2;

    // Top indicator
    canvas.drawLine(
      Offset(center.dx - 20, center.dy - halfH),
      Offset(center.dx + 20, center.dy - halfH),
      cornerPaint,
    );
    // Bottom indicator
    canvas.drawLine(
      Offset(center.dx - 20, center.dy + halfH),
      Offset(center.dx + 20, center.dy + halfH),
      cornerPaint,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
