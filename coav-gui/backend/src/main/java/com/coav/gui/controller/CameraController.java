package com.coav.gui.controller;

import com.coav.gui.model.Camera;
import com.coav.gui.model.CameraVerification;
import com.coav.gui.service.CameraStore;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Collection;
import java.util.List;

@RestController
@RequestMapping("/api")
@CrossOrigin(origins = "*")
@RequiredArgsConstructor
public class CameraController {

    private final CameraStore cameraStore;

    @GetMapping("/cameras")
    public ResponseEntity<List<Camera>> getCameras() {
        return ResponseEntity.ok(CameraStore.CAMERAS);
    }

    @GetMapping("/camera-verification")
    public ResponseEntity<Collection<CameraVerification>> getCameraVerification() {
        return ResponseEntity.ok(cameraStore.getVerifications());
    }
}
