"""
VitalGraph Client Binary Streaming

Generator and consumer classes for efficient file streaming operations.
"""

from abc import ABC, abstractmethod
from typing import Iterator, BinaryIO, Union, Optional
from pathlib import Path
import io


class BinaryGenerator(ABC):
    """Abstract base class for binary data generators."""
    
    @abstractmethod
    def generate(self) -> Iterator[bytes]:
        """Generate binary data chunks."""
        pass
    
    @property
    @abstractmethod
    def content_length(self) -> Optional[int]:
        """Return the total content length if known, None otherwise."""
        pass
    
    @property
    @abstractmethod
    def filename(self) -> Optional[str]:
        """Return the filename if available, None otherwise."""
        pass
    
    @property
    @abstractmethod
    def content_type(self) -> Optional[str]:
        """Return the MIME content type if known, None otherwise."""
        pass


class BinaryConsumer(ABC):
    """Abstract base class for binary data consumers."""
    
    @abstractmethod
    def consume(self, data: bytes) -> None:
        """Consume a chunk of binary data."""
        pass
    
    @abstractmethod
    def finalize(self) -> None:
        """Finalize the consumption process."""
        pass


class FilePathGenerator(BinaryGenerator):
    """Generator that reads from a file path."""
    
    def __init__(self, file_path: Union[str, Path], chunk_size: int = 8192, 
                 content_type: Optional[str] = None):
        self.file_path = Path(file_path)
        self.chunk_size = chunk_size
        self._content_type = content_type
        
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")
    
    def generate(self) -> Iterator[bytes]:
        """Generate chunks from the file."""
        with open(self.file_path, 'rb') as f:
            while True:
                chunk = f.read(self.chunk_size)
                if not chunk:
                    break
                yield chunk
    
    @property
    def content_length(self) -> Optional[int]:
        """Return file size."""
        return self.file_path.stat().st_size
    
    @property
    def filename(self) -> Optional[str]:
        """Return filename."""
        return self.file_path.name
    
    @property
    def content_type(self) -> Optional[str]:
        """Return content type."""
        return self._content_type


class BytesGenerator(BinaryGenerator):
    """Generator that yields from a bytes object."""
    
    def __init__(self, data: bytes, chunk_size: int = 8192, 
                 filename: Optional[str] = None, content_type: Optional[str] = None):
        self.data = data
        self.chunk_size = chunk_size
        self._filename = filename
        self._content_type = content_type
    
    def generate(self) -> Iterator[bytes]:
        """Generate chunks from bytes."""
        for i in range(0, len(self.data), self.chunk_size):
            yield self.data[i:i + self.chunk_size]
    
    @property
    def content_length(self) -> Optional[int]:
        """Return data length."""
        return len(self.data)
    
    @property
    def filename(self) -> Optional[str]:
        """Return filename."""
        return self._filename
    
    @property
    def content_type(self) -> Optional[str]:
        """Return content type."""
        return self._content_type


class StreamGenerator(BinaryGenerator):
    """Generator that reads from a stream/file-like object."""
    
    def __init__(self, stream: BinaryIO, chunk_size: int = 8192, 
                 filename: Optional[str] = None, content_type: Optional[str] = None,
                 content_length: Optional[int] = None):
        self.stream = stream
        self.chunk_size = chunk_size
        self._filename = filename or getattr(stream, 'name', None)
        self._content_type = content_type
        self._content_length = content_length
    
    def generate(self) -> Iterator[bytes]:
        """Generate chunks from stream."""
        while True:
            chunk = self.stream.read(self.chunk_size)
            if not chunk:
                break
            yield chunk
    
    @property
    def content_length(self) -> Optional[int]:
        """Return content length if known."""
        return self._content_length
    
    @property
    def filename(self) -> Optional[str]:
        """Return filename."""
        return self._filename
    
    @property
    def content_type(self) -> Optional[str]:
        """Return content type."""
        return self._content_type


class FilePathConsumer(BinaryConsumer):
    """Consumer that writes to a file path."""
    
    def __init__(self, file_path: Union[str, Path], create_dirs: bool = True):
        self.file_path = Path(file_path)
        self.create_dirs = create_dirs
        self._file_handle = None
        
        if self.create_dirs:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
    
    def consume(self, data: bytes) -> None:
        """Write data chunk to file."""
        if self._file_handle is None:
            self._file_handle = open(self.file_path, 'wb')
        self._file_handle.write(data)
    
    def finalize(self) -> None:
        """Close the file handle."""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None


class BytesConsumer(BinaryConsumer):
    """Consumer that accumulates data into a bytes object."""
    
    def __init__(self):
        self._buffer = io.BytesIO()
        self._finalized = False
    
    def consume(self, data: bytes) -> None:
        """Add data to buffer."""
        if self._finalized:
            raise RuntimeError("Consumer has been finalized")
        self._buffer.write(data)
    
    def finalize(self) -> None:
        """Mark as finalized."""
        self._finalized = True
    
    def get_bytes(self) -> bytes:
        """Get the accumulated bytes."""
        return self._buffer.getvalue()


class StreamConsumer(BinaryConsumer):
    """Consumer that writes to a stream/file-like object."""
    
    def __init__(self, stream: BinaryIO, close_on_finalize: bool = False):
        self.stream = stream
        self.close_on_finalize = close_on_finalize
    
    def consume(self, data: bytes) -> None:
        """Write data to stream."""
        self.stream.write(data)
    
    def finalize(self) -> None:
        """Optionally close the stream."""
        if self.close_on_finalize:
            self.stream.close()


class PumpingGenerator(BinaryGenerator):
    """Generator that pumps data from a consumer to create a generator."""
    
    def __init__(self, source_generator: BinaryGenerator):
        self.source_generator = source_generator
    
    def generate(self) -> Iterator[bytes]:
        """Generate by consuming from source."""
        for chunk in self.source_generator.generate():
            yield chunk
    
    @property
    def content_length(self) -> Optional[int]:
        """Delegate to source."""
        return self.source_generator.content_length
    
    @property
    def filename(self) -> Optional[str]:
        """Delegate to source."""
        return self.source_generator.filename
    
    @property
    def content_type(self) -> Optional[str]:
        """Delegate to source."""
        return self.source_generator.content_type


def pump_data(generator: BinaryGenerator, consumer: BinaryConsumer) -> None:
    """
    Pump data from a generator to a consumer.
    
    Args:
        generator: Source of binary data
        consumer: Destination for binary data
    """
    try:
        for chunk in generator.generate():
            consumer.consume(chunk)
    finally:
        consumer.finalize()


def create_generator(source: Union[str, Path, bytes, BinaryIO, BinaryGenerator], 
                    chunk_size: int = 8192, filename: Optional[str] = None, 
                    content_type: Optional[str] = None, 
                    content_length: Optional[int] = None) -> BinaryGenerator:
    """
    Create a generator from various source types.
    
    Args:
        source: Data source (path, bytes, stream, or existing generator)
        chunk_size: Size of chunks to generate
        filename: Optional filename
        content_type: Optional MIME type
        content_length: Optional content length for streams
        
    Returns:
        BinaryGenerator instance
    """
    if isinstance(source, BinaryGenerator):
        return source
    elif isinstance(source, (str, Path)):
        return FilePathGenerator(source, chunk_size, content_type)
    elif isinstance(source, bytes):
        return BytesGenerator(source, chunk_size, filename, content_type)
    elif hasattr(source, 'read'):
        return StreamGenerator(source, chunk_size, filename, content_type, content_length)
    else:
        raise TypeError(f"Unsupported source type: {type(source)}")


def create_consumer(destination: Union[str, Path, BinaryIO, BinaryConsumer], 
                   create_dirs: bool = True, close_on_finalize: bool = False) -> BinaryConsumer:
    """
    Create a consumer from various destination types.
    
    Args:
        destination: Data destination (path, stream, or existing consumer)
        create_dirs: Whether to create directories for file paths
        close_on_finalize: Whether to close streams on finalize
        
    Returns:
        BinaryConsumer instance
    """
    if isinstance(destination, BinaryConsumer):
        return destination
    elif isinstance(destination, (str, Path)):
        return FilePathConsumer(destination, create_dirs)
    elif hasattr(destination, 'write'):
        return StreamConsumer(destination, close_on_finalize)
    else:
        raise TypeError(f"Unsupported destination type: {type(destination)}")
