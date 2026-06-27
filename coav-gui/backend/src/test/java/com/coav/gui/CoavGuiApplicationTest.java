package com.coav.gui;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

// Use mock profile so context loads without Azure credentials
@SpringBootTest
@ActiveProfiles("mock")
class CoavGuiApplicationTest {

    @Test
    void contextLoads() {
        // Verifies Spring context starts cleanly: all beans wire up, scheduler runs, WebSocket broker initialises
    }
}
