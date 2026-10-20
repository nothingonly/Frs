import 'dart:io';
import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Real Camera Viewport managing physical camera hardware, Android lifecycle, and frame capture.
class CameraViewport extends StatefulWidget {
  final List<Uint8List>? capturedImages;
  final ValueChanged<List<Uint8List>> onImagesCaptured;
  final VoidCallback onRetakePressed;
  final bool isSubmitting;
  final bool isActive;
  final bool canRetake;

  const CameraViewport({
    super.key,
    required this.capturedImages,
    required this.onImagesCaptured,
    required this.onRetakePressed,
    this.isSubmitting = false,
    this.isActive = true,
    this.canRetake = true,
  });

  @override
  State<CameraViewport> createState() => CameraViewportState();
}

class CameraViewportState extends State<CameraViewport> with WidgetsBindingObserver {
  CameraController? _controller;
  List<CameraDescription> _availableCameras = [];
  bool _isInitialized = false;
  bool _isPermissionDenied = false;
  bool _isCapturing = false;
  String? _errorMessage;

  Uint8List? get _previewImage {
    final frames = widget.capturedImages;
    return frames != null && frames.isNotEmpty ? frames.first : null;
  }

  static const int _burstFrameCount = 3;

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

      // Front-facing camera is primary for kiosk attendance. Fallback to back or first.
      final camera = _availableCameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.front,
        orElse: () => _availableCameras.first,
      );

      final controller = CameraController(
        camera,
        ResolutionPreset.medium,
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

  Future<void> _capturePhoto() async {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) return;
    if (_isCapturing || widget.isSubmitting) return;
    setState(() => _isCapturing = true);
    final capturedFrames = <Uint8List>[];
    try {
      // These are distinct hardware exposures over time; never clone an image
      // to manufacture temporal evidence.
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
          } catch (_) {
            // The camera plugin may remove its temporary file itself.
          }
        }
      }
      if (capturedFrames.length != _burstFrameCount) {
        throw StateError('The full $_burstFrameCount-frame capture burst was not completed.');
      }
      if (mounted) {
        widget.onImagesCaptured(List<Uint8List>.unmodifiable(capturedFrames));
      }
    } on CameraException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTheme.errorRed,
            content: Text('Camera burst failed; no frames were submitted: ${e.description ?? e.code}'),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppTheme.errorRed,
            content: Text('Capture burst failed; no frames were submitted: $e'),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isCapturing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
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

          // 2. Oval Biometric Alignment Reticle Overlay (drawn whenever viewing live or captured face)
          IgnorePointer(
            child: CustomPaint(
              size: Size.infinite,
              painter: _FaceReticlePainter(),
            ),
          ),

          // 3. Guidance text banner
          Positioned(
            top: 20,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.black.withOpacity(0.65),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: Colors.white.withOpacity(0.2)),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    _previewImage != null
                        ? Icons.check_circle_outline
                        : (_isInitialized ? Icons.face_rounded : Icons.camera_alt_outlined),
                    color: _previewImage != null ? AppTheme.successGreen : Colors.white,
                    size: 18,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    _previewImage != null
                        ? '${widget.capturedImages?.length ?? 0} Frames Captured — Ready for Verification'
                        : (_isInitialized
                            ? 'Align Face Inside Oval Reticle'
                            : 'Camera Hardware Status'),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
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
                      ),
                      icon: const Icon(Icons.refresh_rounded, size: 20),
                      label: const Text('Retake Photo'),
                    )
                  else if (_isInitialized)
                    ElevatedButton.icon(
                      onPressed: (_isCapturing || widget.isSubmitting) ? null : _capturePhoto,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.primaryBlue,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 16),
                        minimumSize: Size.zero,
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
                        _isCapturing ? 'Capturing...' : 'Capture Face',
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
                  ? 'Grant CAMERA permission in device Settings to enable kiosk attendance.'
                  : 'Please wait while camera sensors are probed.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white.withOpacity(0.5),
                fontSize: 12,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Custom painter rendering a dashed/solid oval biometric alignment guide.
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

    // Corner guides for biometric reticle precision feel
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
