package com.coav.gui.model;

import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class CorrectionValidationTest {

    private static Validator validator;

    @BeforeAll
    static void setup() {
        validator = Validation.buildDefaultValidatorFactory().getValidator();
    }

    @Test
    void validCorrection_noViolations() {
        Correction c = new Correction();
        c.setFlightId("C100-CLB");
        c.setNewAltitudeFt(37000);
        assertThat(validator.validate(c)).isEmpty();
    }

    @Test
    void validCorrection_withOptionalReason_noViolations() {
        Correction c = new Correction();
        c.setFlightId("ABC-123");
        c.setNewAltitudeFt(35000);
        c.setReason("Contrail avoidance");
        assertThat(validator.validate(c)).isEmpty();
    }

    @Test
    void flightId_lowercase_violatesPattern() {
        Correction c = new Correction();
        c.setFlightId("abc-123");
        c.setNewAltitudeFt(35000);
        Set<ConstraintViolation<Correction>> violations = validator.validate(c);
        assertThat(violations).isNotEmpty();
        assertThat(violations).anyMatch(v -> v.getPropertyPath().toString().equals("flightId"));
    }

    @Test
    void flightId_tooShort_violatesSize() {
        Correction c = new Correction();
        c.setFlightId("AB");
        c.setNewAltitudeFt(35000);
        assertThat(validator.validate(c)).isNotEmpty();
    }

    @Test
    void flightId_tooLong_violatesSize() {
        Correction c = new Correction();
        c.setFlightId("ABCDEFGHIJKLM"); // 13 chars, max is 12
        c.setNewAltitudeFt(35000);
        assertThat(validator.validate(c)).isNotEmpty();
    }

    @Test
    void flightId_null_violatesNotBlank() {
        Correction c = new Correction();
        c.setFlightId(null);
        c.setNewAltitudeFt(35000);
        assertThat(validator.validate(c)).isNotEmpty();
    }

    @Test
    void flightId_blank_violatesNotBlank() {
        Correction c = new Correction();
        c.setFlightId("   ");
        c.setNewAltitudeFt(35000);
        assertThat(validator.validate(c)).isNotEmpty();
    }

    @Test
    void altitude_null_violatesNotNull() {
        Correction c = new Correction();
        c.setFlightId("C100-CLB");
        c.setNewAltitudeFt(null);
        assertThat(validator.validate(c)).isNotEmpty();
    }

    @Test
    void altitude_tooHigh_violatesMax() {
        Correction c = new Correction();
        c.setFlightId("C100-CLB");
        c.setNewAltitudeFt(70000);
        assertThat(validator.validate(c)).isNotEmpty();
    }

    @Test
    void altitude_negative_violatesMin() {
        Correction c = new Correction();
        c.setFlightId("C100-CLB");
        c.setNewAltitudeFt(-500);
        assertThat(validator.validate(c)).isNotEmpty();
    }

    @Test
    void altitude_atExactBoundaries_noViolations() {
        Correction low = new Correction();
        low.setFlightId("C100-CLB");
        low.setNewAltitudeFt(0);
        assertThat(validator.validate(low)).isEmpty();

        Correction high = new Correction();
        high.setFlightId("C100-CLB");
        high.setNewAltitudeFt(60000);
        assertThat(validator.validate(high)).isEmpty();
    }
}
