"""
VitalGraph Client Async Binary Streaming

Async generator and consumer classes for efficient file streaming operations.
Compatible with FastAPI and async/await patterns for programmatic chunk pumping.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, BinaryIO, Union, Optional
from pathlib import Path
import aiofiles
import io


class AsyncBinaryGenerator(ABC):
    """Abstract base class for async binary data generators."""
    
    @abstractmethod
    async def generate(self) -> AsyncIterator[bytes]:
        """Generate binary data chunks asynchronously."""
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


class AsyncBinaryConsumer(ABC):
    """Abstract base class for async binary data consumers."""
    
    @abstractmethod
    async def consume(self, data: bytes) -> None:
        """Consume a chunk of binary data asynchronously."""
        pass
    
    @abstractmethod
    async def finalize(self) -> None:
        """Finalize the consumption process asynchronously."""
        pass


class AsyncFilePathGenerator(AsyncBinaryGenerator):
    """Async generator that reads from a file path."""
    
    def __init__(self, file_path: Union[str, Path], chunk_size: int = 8192, 
                 content_type: Optional[str] = None):
        self.file_path = Path(file_path)
        self.chunk_size = chunk_size
        self._content_type = content_type
        
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")
    
    async def generate(self) -> AsyncIterator[bytes]:
        """Generate chunks from the file asynchronously."""
        async with aiofiles.open(self.file_path, 'rb') as f:
            while True:
                chunk = await f.read(self.chunk_size)
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


class AsyncBytesGenerator(AsyncBinaryGenerator):
    """Async generator that yields from a bytes object."""
    
    def __init__(self, data: bytes, chunk_size: int = 8192, 
                 filename: Optional[str] = None, content_type: Optional[str] = None):
        self.data = data
        self.chunk_size = chunk_size
        self._filename = filename
        self._content_type = content_type
    
    async def generate(self) -> AsyncIterator[bytes]:
        """Generate chunks from bytes asynchronously."""
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


class AsyncStreamGenerator(AsyncBinaryGenerator):
    """Async generator that reads from an async iterable or response stream."""
    
    def __init__(self, stream: AsyncIterator[bytes], chunk_size: int = 8192, 
                 filename: Optional[str] = None, content_type: Optional[str] = None,
                 content_length: Optional[int] = None):
        self.stream = stream
        self.chunk_size = chunk_size
        self._filename = filename
        self._content_type = content_type
        self._content_length = content_length
    
    async def generate(self) -> AsyncIterator[bytes]:
        """Generate chunks from async stream."""
        async for chunk in self.stream:
            if chunk:
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


class AsyncFilePathConsumer(AsyncBinaryConsumer):
    """Async consumer that writes to a file path."""
    
    def __init__(self, file_path: Union[str, Path], create_dirs: bool = True):
        self.file_path = Path(file_path)
        self.create_dirs = create_dirs
        self._file_handle = None
        
        if self.create_dirs:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
    
    async def consume(self, data: bytes) -> None:
        """Write data chunk to file asynchronously."""
        if self._file_handle is None:
            self._file_handle = await aiofiles.open(self.file_path, 'wb')
        await self._file_handle.write(data)
    
    async def finalize(self) -> None:
        """Close the file handle asynchronously."""
        if self._file_handle:
            await self._file_handle.close()
            self._file_handle = None


class AsyncBytesConsumer(AsyncBinaryConsumer):
    """Async consumer that accumulates data into a bytes object."""
    
    def __init__(self):
        self._buffer = io.BytesIO()
        self._finalized = False
    
    async def consume(self, data: bytes) -> None:
        """Add data to buffer."""
        if self._finalized:
            raise RuntimeError("Consumer has been finalized")
        self._buffer.write(data)
    
    async def finalize(self) -> None:
        """Mark as finalized."""
        self._finalized = True
    
    def get_bytes(self) -> bytes:
        """Get the accumulated bytes."""
        return self._buffer.getvalue()


class AsyncStreamConsumer(AsyncBinaryConsumer):
    """Async consumer that writes to an async stream/file-like object."""
    
    def __init__(self, stream, close_on_finalize: bool = False):
        self.stream = stream
        self.close_on_finalize = close_on_finalize
    
    async def consume(self, data: bytes) -> None:
        """Write data to stream asynchronously."""
        if hasattr(self.stream, 'write'):
            if hasattr(self.stream.write, '__call__'):
                # Check if write is async
                result = self.stream.write(data)
                if hasattr(result, '__await__'):
                    await result
        else:
            raise TypeError("Stream must have a write method")
    
    async def finalize(self) -> None:
        """Optionally close the stream."""
        if self.close_on_finalize and hasattr(self.stream, 'close'):
            if hasattr(self.stream.close, '__call__'):
                result = self.stream.close()
                if hasattr(result, '__await__'):
                    await result


async def pump_data_async(generator: AsyncBinaryGenerator, consumer: AsyncBinaryConsumer) -> None:
    """
    Pump data from an async generator to an async consumer.
    
    Args:
        generator: Async source of binary data
        consumer: Async destination for binary data
    """
    try:
        async for chunk in generator.generate():
            await consumer.consume(chunk)
    finally:
        await consumer.finalize()


def create_async_generator(source: Union[str, Path, bytes, AsyncIterator[bytes], AsyncBinaryGenerator], 
                           chunk_size: int = 8192, filename: Optional[str] = None, 
                           content_type: Optional[str] = None, 
                           content_length: Optional[int] = None) -> AsyncBinaryGenerator:
    """
    Create an async generator from various source types.
    
    Args:
        source: Data source (path, bytes, async iterator, or existing async generator)
        chunk_size: Size of chunks to generate
        filename: Optional filename
        content_type: Optional MIME type
        content_length: Optional content length for streams
        
    Returns:
        AsyncBinaryGenerator instance
    """
    if isinstance(source, AsyncBinaryGenerator):
        return source
    elif isinstance(source, (str, Path)):
        return AsyncFilePathGenerator(source, chunk_size, content_type)
    elif isinstance(source, bytes):
        return AsyncBytesGenerator(source, chunk_size, filename, content_type)
    elif hasattr(source, '__aiter__'):
        return AsyncStreamGenerator(source, chunk_size, filename, content_type, content_length)
    else:
        raise TypeError(f"Unsupported source type: {type(source)}")


def create_async_consumer(destination: Union[str, Path, AsyncBinaryConsumer], 
                          create_dirs: bool = True, close_on_finalize: bool = False) -> AsyncBinaryConsumer:
    """
    Create an async consumer from various destination types.
    
    Args:
        destination: Data destination (path, stream, or existing async consumer)
        create_dirs: Whether to create directories for file paths
        close_on_finalize: Whether to close streams on finalize
        
    Returns:
        AsyncBinaryConsumer instance
    """
    if isinstance(destination, AsyncBinaryConsumer):
        return destination
    elif isinstance(destination, (str, Path)):
        return AsyncFilePathConsumer(destination, create_dirs)
    elif hasattr(destination, 'write'):
        return AsyncStreamConsumer(destination, close_on_finalize)
    else:
        raise TypeError(f"Unsupported destination type: {type(destination)}")
