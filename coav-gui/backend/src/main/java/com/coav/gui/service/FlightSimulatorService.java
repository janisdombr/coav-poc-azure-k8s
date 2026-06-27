package com.coav.gui.service;

import com.coav.gui.model.Flight;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Profile;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.List;
import java.util.Random;

@Service
@Profile("mock")
@RequiredArgsConstructor
public class FlightSimulatorService {

    private final FlightStateStore store;
    private final Random rng = new Random();
    private long tick = 0;

    @Scheduled(fixedRate = 2000)
    public void tick() {
        tick++;
        long window = System.currentTimeMillis() / 1000 / 300;

        List<String> ids = List.of(
            String.format("C%d-CLB", (window * 3 + 1) % 900 + 100),
            String.format("S%d-CRZ", (window * 3 + 2) % 900 + 100),
            String.format("B%d-DSC", (window * 3 + 3) % 900 + 100)
        );

        double baseLat = 69.23, baseLon = 17.98;
        int[] altitudes = {33000, 35000, 37000};
        String iso = Instant.now().toString();

        for (int i = 0; i < ids.size(); i++) {
            double lat = baseLat + Math.sin(tick * 0.05 + i * 2.1) * 0.4;
            double lon = baseLon + Math.cos(tick * 0.05 + i * 2.1) * 0.4;
            int alt = altitudes[i] + (int) (Math.sin(tick * 0.02 + i) * 500);
            boolean inIssr = store.isInsideIssrZone(lat, lon, alt);
            boolean contrail = inIssr || rng.nextDouble() < 0.15;
            String alert = (contrail && inIssr) ? "CRITICAL" : contrail ? "WARNING" : null;

            store.updateFlight(Flight.builder()
                .flightId(ids.get(i))
                .latitude(lat).longitude(lon)
                .altitudeFt(alt).speedKnots(480 + rng.nextInt(40))
                .contrailDetected(contrail).issrZone(inIssr)
                .alert(alert).timestamp(iso)
                .build());
        }
    }
}
