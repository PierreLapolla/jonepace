import shutil
from pathlib import Path
from pedros import get_logger

logger = get_logger()

def check_disk_space(path: Path, required_size_bytes: int) -> bool:
    """Check if the given path has enough free space."""
    total, used, free = shutil.disk_usage(path)
    
    if free < required_size_bytes:
        logger.error(f"Not enough disk space! Required: {required_size_bytes / (1024**3):.2f} GB, Available: {free / (1024**3):.2f} GB")
        return False
        
    return True

def get_disk_info(path: Path) -> dict:
    """Get disk usage information for a path."""
    total, used, free = shutil.disk_usage(path)
    return {
        "total": total,
        "used": used,
        "free": free
    }
