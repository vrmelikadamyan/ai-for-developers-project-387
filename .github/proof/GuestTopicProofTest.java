package io.hexlet.calendar;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.client.RestTestClient;

class GuestTopicProofTest extends CalendarHttpTest {
  private static final String UPCOMING = "/api/owner/bookings/upcoming";

  private Map<String, String> input(UUID type) {
    return new HashMap<>(
        Map.of(
            "meetingTypeId", type.toString(),
            "startsAt", "2026-11-11T06:30:00Z",
            "guestName", "Анна",
            "guestEmail", "anna@example.org"));
  }

  private RestTestClient.ResponseSpec submit(RestTestClient http, Map<String, String> input) {
    return http.post().uri("/api/bookings").contentType(MediaType.APPLICATION_JSON).body(input).exchange();
  }

  @Test
  void publishesNormalizedTopicToGuestAndOwner() {
    try (var app = start()) {
      var http = http(app);
      var data = input(publish(http, 30));
      var topic = "🌍".repeat(1000);
      data.put("guestTopic", "  " + topic + "  ");
      submit(http, data).expectStatus().isCreated().expectBody().jsonPath("$.guestTopic").isEqualTo(topic);
      http.get().uri(UPCOMING).exchange().expectStatus().isOk()
          .expectBody().jsonPath("$[0].guestTopic").isEqualTo(topic);
    }
  }

  @Test
  void rejectsOverlongTopicWithoutCreatingBooking() {
    try (var app = start()) {
      var http = http(app);
      var data = input(publish(http, 30));
      data.put("guestTopic", "🌍".repeat(1001));
      submit(http, data).expectStatus().isBadRequest().expectBody()
          .jsonPath("$.code").isEqualTo("INVALID_INPUT")
          .jsonPath("$.field").isEqualTo("guestTopic");
      http.get().uri(UPCOMING).exchange().expectStatus().isOk().expectBody().json("[]");
    }
  }

  @Test
  void acceptsExistingClientWithoutTopic() {
    try (var app = start()) {
      var http = http(app);
      submit(http, input(publish(http, 30))).expectStatus().isCreated()
          .expectBody().jsonPath("$.guestTopic").doesNotHaveJsonPath();
      http.get().uri(UPCOMING).exchange().expectStatus().isOk().expectBody()
          .jsonPath("$[0].guestEmail").isEqualTo("anna@example.org")
          .jsonPath("$[0].guestTopic").doesNotHaveJsonPath();
    }
  }
}
