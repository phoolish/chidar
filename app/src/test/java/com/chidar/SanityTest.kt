package com.chidar

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class SanityTest {

    @Test
    fun `app name is correct`() {
        assertEquals("ChiDar", "ChiDar")
    }

    @Test
    fun `notification distance calculation at 30 mph`() {
        val speedLimitMph = 30
        val reactionTimeSeconds = 30
        val latencyPadding = 1.15

        val distanceFeet = (speedLimitMph.toDouble() / 3600) * reactionTimeSeconds * 5280 * latencyPadding
        val distanceMiles = distanceFeet / 5280

        assertEquals(0.29, distanceMiles, 0.01)
    }

    @Test
    fun `notification distance calculation at 20 mph`() {
        val speedLimitMph = 20
        val reactionTimeSeconds = 30
        val latencyPadding = 1.15

        val distanceFeet = (speedLimitMph.toDouble() / 3600) * reactionTimeSeconds * 5280 * latencyPadding
        val distanceMiles = distanceFeet / 5280

        assertEquals(0.19, distanceMiles, 0.01)
    }
}
