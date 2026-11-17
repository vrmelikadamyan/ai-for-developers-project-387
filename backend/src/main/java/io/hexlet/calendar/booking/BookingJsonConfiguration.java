package io.hexlet.calendar.booking;

import com.fasterxml.jackson.annotation.JsonSetter;
import com.fasterxml.jackson.annotation.Nulls;
import io.hexlet.calendar.api.model.BookingInput;
import org.jspecify.annotations.Nullable;
import org.springframework.boot.jackson.autoconfigure.JsonMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
class BookingJsonConfiguration {
  // The optional guest topic is nullable in the contract; allow an explicit null
  // just for that field while keeping strict null handling everywhere else.
  abstract static class BookingInputMixin {
    @JsonSetter(nulls = Nulls.SET)
    public abstract void setGuestTopic(@Nullable String guestTopic);
  }

  @Bean
  JsonMapperBuilderCustomizer bookingInputNulls() {
    return builder -> builder.addMixIn(BookingInput.class, BookingInputMixin.class);
  }
}
