import pandas as pd
import config
from candles import add_patterns


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add atr, sma, std, upper_band, lower_band, rsi columns (signal timeframe)."""
    # 1. ATR (Volatility metric)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=config.ATR_PERIOD).mean()

    # 2. Bollinger Bands
    df['sma'] = df['close'].rolling(window=config.BB_PERIOD).mean()
    df['std'] = df['close'].rolling(window=config.BB_PERIOD).std()
    df['upper_band'] = df['sma'] + (df['std'] * config.BB_STD)
    df['lower_band'] = df['sma'] - (df['std'] * config.BB_STD)

    # 3. RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=config.RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=config.RSI_PERIOD).mean()
    rs = gain / (loss + 1e-9)
    df['rsi'] = 100 - (100 / (1 + rs))

    # 4. Mean-reversion setup flags and how recently one occurred (for candlestick confirmation)
    df['buy_setup'] = (df['close'] <= df['lower_band']) & (df['rsi'] < config.RSI_OVERSOLD)
    df['sell_setup'] = (df['close'] >= df['upper_band']) & (df['rsi'] > config.RSI_OVERBOUGHT)
    look = max(1, config.CANDLE_LOOKBACK)
    df['buy_setup_recent'] = df['buy_setup'].rolling(look, min_periods=1).max().astype(bool)
    df['sell_setup_recent'] = df['sell_setup'].rolling(look, min_periods=1).max().astype(bool)

    # 5. Candlestick patterns
    df = add_patterns(df)
    return df


def compute_trend(df_htf: pd.DataFrame) -> pd.DataFrame:
    """Add trend_ema column (higher timeframe)."""
    df_htf['trend_ema'] = df_htf['close'].ewm(span=config.TREND_EMA_PERIOD, adjust=False).mean()
    return df_htf


def attach_trend(df: pd.DataFrame, df_htf: pd.DataFrame) -> pd.DataFrame:
    """Merge the last *closed* HTF EMA onto each signal-TF bar (no look-ahead).

    An HTF bar that opened at T is only known once it closes, so bar T's EMA is
    aligned to signal bars from T + one HTF period onward. We approximate that by
    shifting the HTF series forward one bar before the asof merge.
    """
    htf = df_htf[['time', 'trend_ema']].copy()
    htf['trend_ema'] = htf['trend_ema'].shift(1)          # use previous closed HTF bar
    htf = htf.dropna()
    out = pd.merge_asof(df.sort_values('time'), htf.sort_values('time'), on='time', direction='backward')
    return out
