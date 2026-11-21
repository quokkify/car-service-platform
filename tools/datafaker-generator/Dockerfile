FROM eclipse-temurin:25.0.5_8-jdk@sha256:884a2f8692cc1e2c7e21f95914adf0ae0eafee9a7eb663a12169cc44468256ec AS builder

WORKDIR /src

COPY gradle gradle
COPY gradlew gradlew.bat settings.gradle.kts build.gradle.kts ./
RUN ./gradlew --no-daemon dependencies >/dev/null

COPY src src
RUN ./gradlew --no-daemon installDist

FROM eclipse-temurin:25.0.5_8-jre@sha256:945247f9d092703e0c6be92243ef3c51640229e23ab34d353c8dcdc73e6cd4e6

RUN groupadd --system csp \
    && useradd --system --gid csp --home-dir /workspace --shell /usr/sbin/nologin csp \
    && mkdir -p /workspace \
    && chown csp:csp /workspace
WORKDIR /workspace
COPY --from=builder --chown=csp:csp /src/build/install/csp-demo-data /opt/csp-demo-data
USER csp

ENTRYPOINT ["/opt/csp-demo-data/bin/csp-demo-data"]
