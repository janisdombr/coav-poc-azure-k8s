package com.coav.gui.service;

import com.coav.gui.model.Camera;
import com.coav.gui.model.CameraVerification;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Collection;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

@ExtendWith(MockitoExtension.class)
class CameraStoreTest {

    @Mock
    SimpMessagingTemplate messagingTemplate;

    @InjectMocks
    CameraStore store;

    private static CameraVerification.CameraVerificationBuilder valid() {
        return CameraVerification.builder()
            .cameraId("CAM-ALPHA")
            .timestamp("2026-07-05T00:00:00Z")
            .contrailDetected(true)
            .confidence(0.87)
            .contrailPixelRatio(0.042)
            .contrailCount(3)
            .newContrailCount(1)
            .frameRef("gvccs_val_00734")
            .maskPngB64("iVBORw0KGgo=");
    }

    // --- Camera network constant (single source of truth, mirrored in emulator.py) ---

    @Test
    void cameras_constantHasFourCamerasWithSpecCoordinates() {
        List<Camera> cams = CameraStore.CAMERAS;
        assertThat(cams).hasSize(4);
        assertThat(cams).extracting(Camera::id)
            .containsExactly("CAM-ALPHA", "CAM-BRAVO", "CAM-EHBK", "CAM-NORTH");
        assertThat(cams.get(0).lat()).isEqualTo(50.60);
        assertThat(cams.get(0).lon()).isEqualTo(4.60);
        assertThat(cams.get(1).lat()).isEqualTo(51.90);
        assertThat(cams.get(1).lon()).isEqualTo(7.00);
        assertThat(cams.get(2).lat()).isEqualTo(50.92);
        assertThat(cams.get(2).lon()).isEqualTo(5.77);
        assertThat(cams.get(3).lat()).isEqualTo(52.30);
        assertThat(cams.get(3).lon()).isEqualTo(6.50);
        assertThat(cams).allSatisfy(c ->
            assertThat(c.elevationCutoffDeg()).isEqualTo(20.0));
    }

    // --- State keyed by camera_id ---

    @Test
    void updateVerification_validPayload_stored() {
        store.updateVerification(valid().build());
        Collection<CameraVerification> got = store.getVerifications();
        assertThat(got).hasSize(1);
        assertThat(got.iterator().next().getCameraId()).isEqualTo("CAM-ALPHA");
    }

    @Test
    void updateVerification_sameCameraId_overwritesToLatest() {
        store.updateVerification(valid().contrailCount(1).build());
        store.updateVerification(valid().contrailCount(5).build());
        Collection<CameraVerification> got = store.getVerifications();
        assertThat(got).hasSize(1);
        assertThat(got.iterator().next().getContrailCount()).isEqualTo(5);
    }

    @Test
    void updateVerification_distinctCameras_keptSeparately() {
        store.updateVerification(valid().build());
        store.updateVerification(valid().cameraId("CAM-BRAVO").build());
        assertThat(store.getVerifications()).hasSize(2);
    }

    // --- 5-minute TTL ---

    @Test
    @SuppressWarnings("unchecked")
    void getVerifications_expiredEntryDropsOutAfterTtl() {
        store.updateVerification(valid().build());
        store.updateVerification(valid().cameraId("CAM-BRAVO").build());

        Map<String, Instant> lastSeen =
            (Map<String, Instant>) ReflectionTestUtils.getField(store, "lastSeen");
        lastSeen.put("CAM-ALPHA", Instant.now().minus(6, ChronoUnit.MINUTES));

        Collection<CameraVerification> got = store.getVerifications();
        assertThat(got).hasSize(1);
        assertThat(got.iterator().next().getCameraId()).isEqualTo("CAM-BRAVO");
    }

    // --- OWASP A03: fail-closed validation of untrusted Event Hub payloads ---

    @Test
    void updateVerification_nullPayload_dropped() {
        store.updateVerification(null);
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_nullCameraId_dropped() {
        store.updateVerification(valid().cameraId(null).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_lowercaseCameraId_dropped() {
        store.updateVerification(valid().cameraId("cam-alpha").build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_injectionCharactersInCameraId_dropped() {
        store.updateVerification(valid().cameraId("CAM;DROP TABLE").build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_cameraIdOver32Chars_dropped() {
        store.updateVerification(valid().cameraId("C".repeat(33)).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_maskOverSizeLimit_dropped() {
        store.updateVerification(valid().maskPngB64("A".repeat(262_145)).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_maskExactlyAtSizeLimit_accepted() {
        store.updateVerification(valid().maskPngB64("A".repeat(262_144)).build());
        assertThat(store.getVerifications()).hasSize(1);
    }

    @Test
    void updateVerification_confidenceAboveOne_dropped() {
        store.updateVerification(valid().confidence(1.01).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_confidenceNegative_dropped() {
        store.updateVerification(valid().confidence(-0.1).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_pixelRatioOutOfUnitRange_dropped() {
        store.updateVerification(valid().contrailPixelRatio(1.5).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_negativeContrailCount_dropped() {
        store.updateVerification(valid().contrailCount(-1).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_negativeNewContrailCount_dropped() {
        store.updateVerification(valid().newContrailCount(-3).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_rejectedPayloadDoesNotOverwritePreviousGoodState() {
        store.updateVerification(valid().contrailCount(3).build());
        store.updateVerification(valid().contrailCount(-1).build());  // rejected
        Collection<CameraVerification> got = store.getVerifications();
        assertThat(got).hasSize(1);
        assertThat(got.iterator().next().getContrailCount()).isEqualTo(3);
    }

    @Test
    void updateVerification_unitBoundaryValuesZeroAndOne_accepted() {
        store.updateVerification(valid()
            .confidence(0.0).contrailPixelRatio(1.0)
            .contrailCount(0).newContrailCount(0).build());
        assertThat(store.getVerifications()).hasSize(1);
    }

    // --- WebSocket broadcast (/topic/cameras) ---

    @Test
    void broadcastState_sendsWhenVerificationsPresent() {
        store.updateVerification(valid().build());
        store.broadcastState();
        verify(messagingTemplate).convertAndSend(eq("/topic/cameras"), any(Collection.class));
    }

    @Test
    void broadcastState_skipsWhenEmpty() {
        store.broadcastState();
        verifyNoInteractions(messagingTemplate);
    }

    // --- OWASP A03: whitelist + upper bounds + eviction (memory-exhaustion DoS defence) ---

    @Test
    void updateVerification_patternValidButUnknownCameraId_dropped() {
        // "CAM-EVIL" matches the shape regex but is not in the known-camera network
        store.updateVerification(valid().cameraId("CAM-EVIL").build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_contrailCountAboveMax_dropped() {
        store.updateVerification(valid().contrailCount(501).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_newContrailCountAboveMax_dropped() {
        store.updateVerification(valid().newContrailCount(501).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_frameRefInvalidCharset_dropped() {
        store.updateVerification(valid().frameRef("GVCCS VAL 007").build());  // spaces + uppercase
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    void updateVerification_frameRefOver64Chars_dropped() {
        store.updateVerification(valid().frameRef("a".repeat(65)).build());
        assertThat(store.getVerifications()).isEmpty();
    }

    @Test
    @SuppressWarnings("unchecked")
    void broadcastState_evictsExpiredKeysFromBackingMaps() {
        store.updateVerification(valid().build());                       // CAM-ALPHA
        store.updateVerification(valid().cameraId("CAM-BRAVO").build());

        Map<String, Instant> lastSeen =
            (Map<String, Instant>) ReflectionTestUtils.getField(store, "lastSeen");
        Map<String, CameraVerification> verifications =
            (Map<String, CameraVerification>) ReflectionTestUtils.getField(store, "verifications");
        lastSeen.put("CAM-ALPHA", Instant.now().minus(6, ChronoUnit.MINUTES));

        store.broadcastState();  // runs evictExpired()

        // Stale key physically removed from BOTH maps (not just filtered at read time)
        assertThat(verifications).doesNotContainKey("CAM-ALPHA");
        assertThat(lastSeen).doesNotContainKey("CAM-ALPHA");
        assertThat(verifications).containsKey("CAM-BRAVO");
    }
}
