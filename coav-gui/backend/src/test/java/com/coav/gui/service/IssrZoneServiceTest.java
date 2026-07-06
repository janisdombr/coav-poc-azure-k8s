package com.coav.gui.service;

import com.coav.gui.model.IssrZone;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(MockitoExtension.class)
class IssrZoneServiceTest {

    @Mock
    FlightStateStore store;

    @InjectMocks
    IssrZoneService service;

    @Test
    void rhiFromRhw_warmAirReturnsSameValue() {
        // Above 0°C ice physics don't apply — RHi equals RHw
        double result = IssrZoneService.rhiFromRhw(80.0, 5.0);
        assertThat(result).isEqualTo(80.0);
    }

    @Test
    void rhiFromRhw_coldDryAirBelowThreshold() {
        // At -40°C, 50% RHw → RHi should be well below 100% (not ISSR)
        double result = IssrZoneService.rhiFromRhw(50.0, -40.0);
        assertThat(result).isLessThan(100.0);
    }

    @Test
    void rhiFromRhw_coldHumidAirExceedsThreshold() {
        // At -50°C, 70% RHw → RHi > 100% (ISSR conditions)
        double result = IssrZoneService.rhiFromRhw(70.0, -50.0);
        assertThat(result).isGreaterThan(100.0);
    }

    @Test
    void rhiFromRhw_zeroRhwReturnsZero() {
        double result = IssrZoneService.rhiFromRhw(0.0, -50.0);
        assertThat(result).isEqualTo(0.0);
    }

    @Test
    void rhiFromRhw_negativeRhwReturnsUnchanged() {
        // Guard branch: rhwPct <= 0 returns as-is
        double result = IssrZoneService.rhiFromRhw(-5.0, -50.0);
        assertThat(result).isEqualTo(-5.0);
    }

    // --- Zone extent capping: widespread ISSR must not become a single FIR-wide blob ---

    @Test
    void clusterToZones_wallToWallIssr_producesCappedCompactZones() {
        // Same grid bounds/steps as computeGrid(): LAT 49.5-53.5 (6 rows), LON 2.0-10.0 (8 cols)
        double latMin = 49.5, latMax = 53.5;
        double lonMin = 2.0,  lonMax = 10.0;
        int gridLat = 6, gridLon = 8;
        double latStep = (latMax - latMin) / (gridLat - 1);
        double lonStep = (lonMax - lonMin) / (gridLon - 1);

        List<IssrZoneService.GridPoint> allIssr = new ArrayList<>();
        for (int i = 0; i < gridLat; i++) {
            double lat = latMin + i * latStep;
            for (int j = 0; j < gridLon; j++) {
                double lon = lonMin + j * lonStep;
                // Every single grid cell is above the ISSR threshold (RHi 150%) —
                // the pathological "entire FIR is ISSR" case seen live.
                allIssr.add(new IssrZoneService.GridPoint(lat, lon, "250hPa", 34_000, -50.0, 80.0, 150.0));
            }
        }

        List<IssrZone> zones = service.clusterToZones(allIssr);

        assertThat(zones).isNotEmpty();
        for (IssrZone z : zones) {
            double latSpan = z.getMaxLat() - z.getMinLat();
            double lonSpan = z.getMaxLon() - z.getMinLon();
            // Capped extent — small epsilon for rounding (round2)
            assertThat(latSpan).isLessThanOrEqualTo(1.2 + 0.05);
            assertThat(lonSpan).isLessThanOrEqualTo(1.8 + 0.05);
            // Must not cover the whole FIR bounding box
            assertThat(latSpan).isLessThan(latMax - latMin);
            assertThat(lonSpan).isLessThan(lonMax - lonMin);
        }
    }
}
