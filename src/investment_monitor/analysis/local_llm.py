"""Local LLM integration using Ollama for news analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from .prompts import SENTIMENT_PROMPT

if TYPE_CHECKING:
    import ollama


class LocalLLM:
    """Client wrapper for Ollama local LLM inference.

    Provides headline sentiment classification with a local Ollama model.
    """

    def __init__(
        self,
        model: str = "phi3:mini",
        base_url: str = "http://localhost:11434",
    ) -> None:
        """Initialize the LocalLLM client.

        Args:
            model: The Ollama model to use (default: phi3:mini)
            base_url: The Ollama server URL (default: http://localhost:11434)
        """
        self.model = model
        self.base_url = base_url
        self._client: ollama.Client | None = None
        self._available: bool | None = None

    @property
    def client(self) -> ollama.Client:
        """Lazily initialize and return the Ollama client."""
        if self._client is None:
            try:
                import ollama
                self._client = ollama.Client(host=self.base_url)
            except ImportError:
                logger.warning("ollama package not installed, LLM features unavailable")
                raise
        return self._client

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is available.

        Returns:
            True if Ollama is running and model is loaded, False otherwise.
        """
        try:
            import ollama
            client = ollama.Client(host=self.base_url)
            # List models to check if server is running
            response = client.list()

            # Handle both old dict-based API and new object-based API
            model_names: list[str] = []
            if hasattr(response, "models"):
                # New API: response.models is a list of Model objects
                for m in response.models:
                    # Model object has 'model' attribute (e.g., "phi3:mini")
                    name = getattr(m, "model", None) or getattr(m, "name", "")
                    if name:
                        model_names.append(name)
            elif isinstance(response, dict):
                # Old API: response is a dict with "models" key
                for m in response.get("models", []):
                    name = m.get("name", "") or m.get("model", "")
                    if name:
                        model_names.append(name)

            # Check if our model is available (handle both full and short names)
            # e.g., "phi3:mini" should match "phi3:mini" or "phi3:latest"
            base_model = self.model.split(":")[0]
            for name in model_names:
                if name == self.model or name.startswith(base_model):
                    self._available = True
                    return True

            # Model not found but server is running
            logger.warning(f"Model {self.model} not found in Ollama. Available: {model_names}")
            self._available = False
            return False

        except ImportError:
            logger.warning("ollama package not installed")
            self._available = False
            return False
        except Exception as e:
            logger.debug(f"Ollama not available: {e}")
            self._available = False
            return False

    def _generate(self, prompt: str) -> str | None:
        """Generate a response from the LLM.

        Args:
            prompt: The prompt to send to the LLM.

        Returns:
            The LLM response text, or None if unavailable.
        """
        try:
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                options={
                    "temperature": 0.1,  # Low temperature for more deterministic output
                    "num_predict": 50,   # Limit response length
                },
            )
            return response.get("response", "").strip()
        except Exception as e:
            logger.debug(f"LLM generation failed: {e}")
            return None

    async def classify_sentiment(
        self,
        text: str,
    ) -> str:
        """Classify the sentiment of a financial text.

        Args:
            text: The text to analyze (headline or short article).

        Returns:
            One of 'bullish', 'bearish', 'neutral', or 'unknown' if unavailable.
        """
        if not self.is_available():
            return "unknown"
        return self.sentiment(text)

    def sentiment(self, text: str) -> str:
        """Synchronous sentiment classification; the caller checks availability."""
        response = self._generate(SENTIMENT_PROMPT.format(headline=text))
        if response is None:
            return "unknown"
        return self._parse_sentiment(response)

    @staticmethod
    def _parse_sentiment(response: str) -> str:
        """Parse sentiment classification from LLM response.

        Handles various formats:
        - Clean: "bullish"
        - With text: "Sentiment: bullish"
        - Verbose: "I would classify this as bullish"

        Args:
            response: The raw LLM response.

        Returns:
            One of 'bullish', 'bearish', 'neutral', or 'unknown'.
        """
        if not response:
            return "unknown"

        response = response.strip().lower()

        # Check for each sentiment keyword
        if "bullish" in response:
            return "bullish"
        elif "bearish" in response:
            return "bearish"
        elif "neutral" in response:
            return "neutral"

        # Try to match positive/negative synonyms
        positive_words = ["positive", "good", "up", "gain"]
        negative_words = ["negative", "bad", "down", "loss", "decline"]

        for word in positive_words:
            if word in response:
                return "bullish"

        for word in negative_words:
            if word in response:
                return "bearish"

        return "unknown"


def resolve_installed_model(preferred: str, base_url: str | None = None) -> str:
    """Return ``preferred`` if Ollama has it, else an installed model of the same family.

    Same family means the same name before the ``:`` tag (``qwen2.5:7b`` resolves to
    an installed ``qwen2.5:14b``). When Ollama cannot be queried the configured name
    is returned unchanged and the caller's availability check decides.
    """
    try:
        import ollama

        client = ollama.Client(host=base_url) if base_url else ollama.Client()
        installed = [m.model for m in client.list().models]
    except Exception:  # noqa: BLE001 - cannot list -> trust the configured name
        return preferred
    if not installed or preferred in installed:
        return preferred
    base = preferred.split(":")[0]
    family = [m for m in installed if m.split(":")[0] == base]
    return family[0] if family else preferred
