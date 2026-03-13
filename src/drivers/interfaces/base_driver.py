from abc import ABC, abstractmethod

class BaseDriver(ABC):
    def __init__(self, kernel, interface_id: str = "unknown"):
        """
        Initialize the driver.
        :param kernel: Reference to the Kernel class (for callbacks).
        :param interface_id: Unique identifier for the interface (e.g. 'telegram', 'voice').
        """
        self.kernel = kernel
        self.interface_id = interface_id

    def get_interface_id(self) -> str:
        return self.interface_id

    @abstractmethod
    def start(self):
        """
        Start the driver (e.g., start listening loop, polling).
        This should be non-blocking (or run in a thread).
        """
        pass

    @abstractmethod
    def stop(self):
        """
        Stop the driver and release resources.
        """
        pass

    @abstractmethod
    def send_response(self, text, target=None, is_chunk=False, attachments=None):
        """
        Send a response back to the user via this driver.
        :param text: The text message to send.
        :param target: User ID or Channel ID to send to.
        :param is_chunk: Whether this is a partial response or a chunk.
        :param attachments: List of absolute file paths to send with the response.
        """
        pass

    @abstractmethod
    def send_file(self, target, file_path, caption=None):
        """
        Sends a file attachment to the user.
        :param target: User ID or Channel ID to send to.
        :param file_path: Absolute path to the file.
        :param caption: Optional caption text.
        """
        pass

    @abstractmethod
    def send_status(self, target, phase, payload=None):
        """
        Sends a status update (thinking, planning, error, etc.) to the user.
        :param target: User ID or Channel ID to send to.
        :param phase: The string identifier of the phase ("thinking", "executing", "error").
        :param payload: A dictionary containing structured context about the phase or error.
        """
        pass

    @abstractmethod
    def send_reasoning_chunk(self, target, content):
        """
        Sends a short reasoning log entry.
        """
        pass

    @abstractmethod
    def send_complete(self, target):
        """
        Sends a completion event to close loaders/streams.
        """
        pass


    def on_message_received(self, text, **kwargs):
        """
        Callback to notify Kernel that a message was received.
        """
        if self.kernel:
            return self.kernel.process_input(text, self, **kwargs)

    def get_capabilities(self) -> dict:
        """
        Returns a dictionary of driver capabilities affecting agent behavior and formatting.
        Defaults to assuming the interface supports rich text and markdown.
        """
        return {
            "markdown": True,
            "rich_media": True,
            "voice_only": False,
            "streaming": False
        }
