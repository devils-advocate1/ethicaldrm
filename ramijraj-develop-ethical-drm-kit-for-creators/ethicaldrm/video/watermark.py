"""
Video Watermarking Module for EthicalDRM

Provides invisible watermarking using LSB (Least Significant Bit) encoding
and motion blur patterns for user identification and leak detection.
"""

import cv2
import numpy as np
import ffmpeg
import os
import hashlib
import logging
from typing import Optional, Tuple, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class Watermarker:
    """
    Invisible video watermarking for user identification and leak detection.
    
    Features:
    - LSB encoding in video frames
    - Motion blur pattern watermarks
    - Per-user dynamic watermarks
    - Minimal visual impact
    """
    
    def __init__(self, user_id: str, method: str = "lsb", strength: float = 0.1):
        """
        Initialize watermarker with user identification.
        
        Args:
            user_id: Unique identifier for the user
            method: Watermarking method ('lsb' or 'motion_blur')
            strength: Watermark strength (0.0 to 1.0)
        """
        self.user_id = user_id
        self.method = method
        self.strength = strength
        self.watermark_signature = self._generate_signature()
        
    def _generate_signature(self) -> str:
        """Generate unique signature for the user."""
        combined = f"{self.user_id}_{self.method}_{self.strength}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]
    
    def _embed_lsb_watermark(self, frame: np.ndarray, watermark_data: str) -> np.ndarray:
        """
        Embed watermark using LSB encoding in the blue channel.
        
        Args:
            frame: Video frame as numpy array
            watermark_data: Data to embed
            
        Returns:
            Watermarked frame
        """
        height, width = frame.shape[:2]
        
        # Convert watermark to binary
        watermark_binary = ''.join(format(ord(char), '08b') for char in watermark_data)
        watermark_binary += '1111111111111110'  # End marker
        
        # Embed in blue channel LSB
        watermarked_frame = frame.copy()
        data_index = 0
        
        for y in range(height):
            for x in range(width):
                if data_index < len(watermark_binary):
                    # Modify LSB of blue channel
                    pixel = watermarked_frame[y, x]
                    blue_channel = pixel[0]
                    
                    # Clear LSB and set new bit
                    blue_channel = (blue_channel & 0xFE) | int(watermark_binary[data_index])
                    watermarked_frame[y, x, 0] = blue_channel
                    
                    data_index += 1
                else:
                    break
            if data_index >= len(watermark_binary):
                break
                
        return watermarked_frame
    
    def _embed_motion_blur_watermark(self, frame: np.ndarray) -> np.ndarray:
        """
        Embed subtle motion blur pattern based on user signature.
        
        Args:
            frame: Video frame as numpy array
            
        Returns:
            Watermarked frame with motion blur pattern
        """
        watermarked_frame = frame.copy().astype(np.float32)
        height, width = frame.shape[:2]
        
        # Generate pattern based on user signature
        pattern_seed = int(self.watermark_signature[:8], 16)
        np.random.seed(pattern_seed)
        
        # Create subtle motion blur kernel
        kernel_size = 3
        angle = (pattern_seed % 180) * np.pi / 180
        kernel = np.zeros((kernel_size, kernel_size))
        
        # Create directional blur based on signature
        for i in range(kernel_size):
            x = int(i * np.cos(angle))
            y = int(i * np.sin(angle))
            if 0 <= x < kernel_size and 0 <= y < kernel_size:
                kernel[x, y] = 1
                
        kernel = kernel / np.sum(kernel) if np.sum(kernel) > 0 else kernel
        
        # Apply selective blur to specific regions
        region_size = 16
        for y in range(0, height - region_size, region_size * 4):
            for x in range(0, width - region_size, region_size * 4):
                if (x + y + pattern_seed) % 8 == 0:  # Sparse application
                    region = watermarked_frame[y:y+region_size, x:x+region_size]
                    blurred_region = cv2.filter2D(region, -1, kernel)
                    
                    # Blend with original (very subtle)
                    alpha = self.strength * 0.1
                    watermarked_frame[y:y+region_size, x:x+region_size] = (
                        alpha * blurred_region + (1 - alpha) * region
                    )
        
        return watermarked_frame.astype(np.uint8)
    
    def embed(self, input_path: str, output_path: str, 
              frame_interval: int = 30) -> Dict[str, Any]:
        """
        Embed watermark in video file.
        
        Args:
            input_path: Path to input video
            output_path: Path to output watermarked video
            frame_interval: Watermark every N frames
            
        Returns:
            Dictionary with embedding results
        """
        try:
            logger.info(f"Starting watermark embedding for user {self.user_id}")
            
            # Open video
            cap = cv2.VideoCapture(input_path)
            if not cap.isOpened():
                raise ValueError(f"Cannot open video file: {input_path}")
            
            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # Setup video writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            
            frame_count = 0
            watermarked_frames = 0
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Apply watermark every frame_interval frames
                if frame_count % frame_interval == 0:
                    if self.method == "lsb":
                        watermark_data = f"{self.user_id}:{self.watermark_signature}:{frame_count}"
                        frame = self._embed_lsb_watermark(frame, watermark_data)
                    elif self.method == "motion_blur":
                        frame = self._embed_motion_blur_watermark(frame)
                    
                    watermarked_frames += 1
                
                out.write(frame)
                frame_count += 1
                
                if frame_count % 100 == 0:
                    logger.info(f"Processed {frame_count}/{total_frames} frames")
            
            cap.release()
            out.release()
            
            result = {
                'success': True,
                'user_id': self.user_id,
                'signature': self.watermark_signature,
                'method': self.method,
                'total_frames': frame_count,
                'watermarked_frames': watermarked_frames,
                'output_path': output_path,
                'file_size': os.path.getsize(output_path)
            }
            
            logger.info(f"Watermarking completed: {watermarked_frames} frames processed")
            return result
            
        except Exception as e:
            logger.error(f"Watermarking failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'user_id': self.user_id
            }
    
    def extract_watermark(self, video_path: str, method: str = None) -> Optional[Dict[str, str]]:
        """
        Extract watermark information from video.
        
        Args:
            video_path: Path to watermarked video
            method: Extraction method (auto-detect if None)
            
        Returns:
            Extracted watermark data or None if not found
        """
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None
            
            extraction_method = method or self.method
            
            # Try to extract from first few frames
            for frame_idx in range(min(100, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx * 30)  # Sample every 30 frames
                ret, frame = cap.read()
                if not ret:
                    break
                
                if extraction_method == "lsb":
                    extracted = self._extract_lsb_watermark(frame)
                    if extracted:
                        cap.release()
                        return extracted
            
            cap.release()
            return None
            
        except Exception as e:
            logger.error(f"Watermark extraction failed: {str(e)}")
            return None
    
    def _extract_lsb_watermark(self, frame: np.ndarray) -> Optional[Dict[str, str]]:
        """
        Extract LSB watermark from frame.
        
        Args:
            frame: Video frame
            
        Returns:
            Extracted watermark data
        """
        height, width = frame.shape[:2]
        binary_data = ""
        
        for y in range(height):
            for x in range(width):
                blue_channel = frame[y, x, 0]
                binary_data += str(blue_channel & 1)
                
                # Check for end marker
                if binary_data.endswith('1111111111111110'):
                    binary_data = binary_data[:-16]  # Remove end marker
                    
                    # Convert binary to text
                    try:
                        text_data = ""
                        for i in range(0, len(binary_data), 8):
                            byte = binary_data[i:i+8]
                            if len(byte) == 8:
                                char = chr(int(byte, 2))
                                text_data += char
                        
                        # Parse watermark data
                        parts = text_data.split(':')
                        if len(parts) >= 2:
                            return {
                                'user_id': parts[0],
                                'signature': parts[1],
                                'frame_number': parts[2] if len(parts) > 2 else 'unknown',
                                'extracted_text': text_data
                            }
                    except:
                        pass
                    
                    return None
        
        return None
    
    def verify_integrity(self, video_path: str) -> Dict[str, Any]:
        """
        Verify video integrity and watermark presence.
        
        Args:
            video_path: Path to video file
            
        Returns:
            Verification results
        """
        result = {
            'file_exists': os.path.exists(video_path),
            'watermark_found': False,
            'user_verified': False,
            'integrity_score': 0.0
        }
        
        if not result['file_exists']:
            return result
        
        # Extract watermark
        watermark_data = self.extract_watermark(video_path)
        if watermark_data:
            result['watermark_found'] = True
            result['extracted_user_id'] = watermark_data.get('user_id')
            result['user_verified'] = watermark_data.get('user_id') == self.user_id
            
            if result['user_verified']:
                result['integrity_score'] = 1.0
            else:
                result['integrity_score'] = 0.5
        
        return result