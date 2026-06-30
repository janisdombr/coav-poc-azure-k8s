package com.coav.gui.controller;

import com.coav.gui.model.Flight;
import com.coav.gui.model.IssrZone;
import com.coav.gui.service.FlightStateStore;
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
public class FlightController {

    private final FlightStateStore flightStateStore;

    @GetMapping("/flights")
    public ResponseEntity<Collection<Flight>> getFlights() {
        return ResponseEntity.ok(flightStateStore.getAllFlights());
    }

    @GetMapping("/issr-zones")
    public ResponseEntity<List<IssrZone>> getIssrZones() {
        return ResponseEntity.ok(flightStateStore.getIssrZones());
    }
}
