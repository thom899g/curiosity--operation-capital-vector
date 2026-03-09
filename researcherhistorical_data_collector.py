"""
Historical Data Collector Module
Collects and processes historical CEX/DEX price data for ML training
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging
from datetime import datetime, timedelta
import asyncio
import aiohttp
from dataclasses import dataclass
import json

# Import from our Firebase setup
import sys
sys.path.append('..')
from firebase_setup import firebase_manager

logger = logging.getLogger(__name__)

@dataclass
class TokenConfig:
    """Configuration for token data collection"""
    symbol: str
    cex_pair: str  # e.g., "ETH/USDT"
    dex_address: str  # Contract address on Base
    dex_pool_fee: int  # Uniswap V3 pool fee tier (500 = 0.05%)
    min_liquidity_usd: float = 100000  # Minimum liquidity threshold

class HistoricalDataCollector:
    """Collects historical arbitrage opportunity data"""
    
    def __init__(self, tokens: List[TokenConfig]):
        """
        Initialize collector with token configurations
        
        Args:
            tokens: List of TokenConfig objects to monitor
        """
        self.tokens = tokens
        self.db = firebase_manager.get_db()
        
        # Initialize CCXT exchange (Coinbase Pro)
        import ccxt
        self.cex = ccxt.coinbasepro({
            'enableRateLimit': True,
            'rateLimit': 100,  # Respect rate limits
            'timeout': 30000
        })
        
        # Web3 provider for Base
        from web3 import Web3
        self.web3 = Web3(Web3.HTTPProvider('https://mainnet.base.org'))
        
        logger.info(f"Initialized HistoricalDataCollector for {len(tokens)} tokens")
    
    async def collect_batch(self, 
                          hours_back: int = 24,
                          interval_minutes: int = 1) -> Dict[str, pd.DataFrame]:
        """
        Collect historical data for specified time period
        
        Args:
            hours_back: How many hours of historical data to collect
            interval_minutes: Data interval in minutes
            
        Returns:
            Dictionary mapping token symbols to DataFrames
        """
        results = {}
        
        for token in self.tokens:
            try:
                logger.info(f"Collecting data for {token.symbol}")
                
                # Collect CEX data
                cex_data = await self._collect_cex_data(
                    token.cex_pair, 
                    hours_back, 
                    interval_minutes
                )
                
                # Collect DEX data (simplified - would use TheGraph in production)
                dex_data = await self._simulate_dex_data(
                    token, 
                    hours_back, 
                    interval_minutes
                )
                
                # Merge and calculate arbitrage opportunities
                merged_data = self._merge_and_calculate(cex_data, dex_data, token)
                
                # Store in Firebase
                await self._store_historical_data(token.symbol, merged_data)
                
                results[token.symbol] = merged_data
                logger.info(f"Completed collection for {token.symbol}: {len(merged_data)} records")
                
            except Exception as e:
                logger.error(f"Failed to collect data for {token.symbol}: {e}", exc_info=True)
                continue
        
        return results
    
    async def _collect_cex_data(self, 
                              pair: str, 
                              hours_back: int,
                              interval_minutes: int) -> pd.DataFrame:
        """Collect OHLCV data from CEX"""
        try:
            since = int((datetime.now() - timedelta(hours=hours_back)).timestamp() * 1000)
            
            # Fetch OHLCV data
            ohlcv = self.cex.fetch_ohlcv(
                pair,
                timeframe=f'{interval_minutes}m',
                since=since,
                limit=1000
            )
            
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Calculate additional features
            df['returns'] = df['close'].pct_change()
            df['volatility'] = df['returns'].rolling(window=20).std()
            df['volume_ma'] = df['volume'].rolling(window=20).mean()
            
            return df
            
        except Exception as e:
            logger.error(f"Failed to collect CEX data for {pair}: {e}")
            raise
    
    async def _simulate_dex_data(self,
                               token: TokenConfig,
                               hours_back: int,
                               interval_minutes: int) -> pd.DataFrame:
        """
        Simulate DEX data collection
        In production, this would query TheGraph or directly from blockchain
        """
        try:
            # Generate synthetic DEX data with latency simulation
            # In reality, this would come from Uniswap V3 subgraph
            
            periods = int((hours_back * 60) / interval_minutes)
            base_price = 1800 if 'ETH' in token.symbol else 1.0  # Mock prices
            
            timestamps = pd.date_range(
                end=datetime.now(),
                periods=periods,
                freq=f'{interval_minutes}min'
            )
            
            # Simulate DEX prices with random walk and latency
            np.random.seed(42)  # For reproducibility
            returns = np.random.normal(0.0001, 0.005, periods)
            prices = base_price * (1 + returns).cumprod()
            
            # Add simulated latency effects (DEX lags behind CEX by 0-300ms)
            latency = np.random.randint(0, 300, periods) / 1000  # Convert to seconds
            latency_shift = np.random.choice([-1, 1], periods) * latency * prices * 0.001
            
            df = pd.DataFrame({
                'timestamp': timestamps,
                'dex_price': prices + latency_shift,
                'dex_liquidity': np.random.uniform(50000, 500000, periods),
                'dex_slippage': np.random.uniform(0.001, 0.01, periods)
            })
            
            df.set_index('timestamp', inplace=True)
            return df
            
        except Exception as e:
            logger.error(f"Failed to simulate DEX data for {token.symbol}: {e}")
            raise
    
    def _merge_and_calculate(self,
                           cex_data: pd.DataFrame,
                           dex_data: pd.DataFrame,
                           token: TokenConfig) -> pd.DataFrame:
        """Merge CEX and DEX data and calculate arbitrage metrics"""
        try:
            # Merge on timestamp (nearest)
            merged = pd.merge_asof(
                cex_data.sort_index(),
                dex_data.sort_index(),
                left_index=True,
                right_index=True,
                direction='nearest',
                tolerance=pd.Timedelta(f'{int((cex_data.index[1] - cex_data.index[0]).total_seconds() / 2)}s')
            )
            
            # Calculate arbitrage opportunities
            merged['price_gap'] = merged['close'] - merged['dex_price']
            merged['gap_percent'] = (merged['price_gap'] / merged['close']) * 100
            merged['gap_abs'] = merged['price_gap'].abs()
            
            # Calculate convergence (did gap close within next period?)
            merged['converged_next'] = (merged['gap_percent'].shift(-1).abs() < 
                                       merged