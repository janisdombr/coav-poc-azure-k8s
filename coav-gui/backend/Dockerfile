# Stage 1: build with Maven (no local mvn required)
FROM maven:3.9-eclipse-temurin-21-alpine AS build
WORKDIR /build
COPY pom.xml .
RUN mvn dependency:go-offline -q
COPY src ./src
RUN mvn package -DskipTests -q

# Stage 2: minimal JRE runtime
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /build/target/coav-gui-backend-*.jar app.jar
# OWASP Container Security: run as non-root (mirrors backend/Dockerfile pattern)
USER 10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
