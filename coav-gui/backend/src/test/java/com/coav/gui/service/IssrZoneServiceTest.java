package com.coav.gui.service;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class IssrZoneServiceTest {

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
}
