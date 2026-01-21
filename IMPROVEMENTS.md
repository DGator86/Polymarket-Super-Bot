# Bot Improvement Report

## 1. Simulation & Evaluation Upgrade
I have created `run_advanced_simulation.py` to address the critical flaws in the previous evaluation.

**Key Features:**
*   **Credible Metrics**: Now calculates **Wilson Score Interval** (95% CI) for win rates, **Brier Score** for calibration, and **Log Loss**.
*   **Regime Analysis**: Automatically splits performance into "Trending" vs "Choppy" markets.
*   **EV-Based Logic**: Simulates trading based on Expected Value ($p - q - fees$) rather than just raw probability.
*   **Reliability Diagram**: Outputs calibration buckets (Predicted vs Actual) to detect overconfidence.

**How to Run:**
```bash
python3 run_advanced_simulation.py
```

**Using Real Data:**
The script is ready for your historical data.
1.  Export your 15m BTC data to a CSV with columns: `timestamp`, `price`.
2.  Modify the `run_simulation` function in `run_advanced_simulation.py`:
    ```python
    # df = gen.generate(days=180)  # Comment this out
    df = SyntheticDataGenerator.load_csv("path/to/your_btc_15m.csv") # Use this
    ```

## 2. Bot Implementation Review
*   **Current Logic**: The `ProbabilityEngine` correctly calculates EV (`p - q - fees`) and sorts opportunities by it.
*   **Improvement**: The `min_edge` is currently static. I recommend updating `config.py` to allow a dynamic `min_edge` that scales with volatility (e.g., `min_edge = base_edge * (volatility / avg_volatility)`).

## 3. Next Steps
1.  **Validate on Real Data**: Run the new simulation script with your real BTC history.
2.  **Check Calibration**: If Brier Score > 0.20, your model is likely random or miscalibrated.
3.  **Adjust Thresholds**: Use the "Reliability Buckets" output to find the true "high confidence" zone (e.g., maybe 0.70 is only 55% actual win rate).
