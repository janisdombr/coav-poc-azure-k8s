package com.coav.gui;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class CoavGuiApplication {
    public static void main(String[] args) {
        SpringApplication.run(CoavGuiApplication.class, args);
    }
}
