package com.coav.gui.model;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class Correction {
    // OWASP A03:2021-Injection — same pattern constraint as emulator.py ADSBTelemetry.flight_id
    @NotBlank
    @Size(min = 3, max = 12)
    @Pattern(regexp = "^[A-Z0-9\\-]+$")
    private String flightId;

    @NotNull
    @Min(0)
    @Max(60000)
    private Integer newAltitudeFt;

    // OWASP A03:2021-Injection — optional free text, length-bounded and restricted to plain ATC
    // phrasing. Allows any Unicode letter/number (\p{L}\p{N}: EU languages, Cyrillic, umlauts) plus
    // em/en dash, so legitimate free text never 400s during a live demo, while still blocking
    // injection metacharacters (< > ; " ' { } & etc. remain outside the class).
    @Size(max = 200)
    @Pattern(regexp = "^[\\p{L}\\p{N} .,()/+\\-:°–—]*$")
    private String reason;
}
