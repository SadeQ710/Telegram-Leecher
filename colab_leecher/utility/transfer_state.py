# Correct content for: colab_leecher/utility/transfer_state.py

class Transfer:
    """Holds state related to file transfer progress and results."""
    down_bytes = [0] # Use a list starting with 0, append actual sizes
    up_bytes = [0]   # Use a list starting with 0, append actual sizes
    total_down_size = 0 # Can be pre-calculated or updated after download
    sent_file = [] # List of successfully sent message objects (from Pyrogram)
    sent_file_names = [] # List of corresponding filenames for logs
    # <<< ADD THIS LINE >>>
    successful_downloads = [] # List to store {'url': url, 'filename': filename} for successful downloads

    def reset(self):
        """Resets the state for a new task."""
        self.down_bytes = [0]
        self.up_bytes = [0]
        self.total_down_size = 0
        self.sent_file = []
        self.sent_file_names = []
        # <<< ADD THIS LINE >>>
        self.successful_downloads = [] # Reset the new list too
