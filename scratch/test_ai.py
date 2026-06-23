import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.ai.client import is_ai_enabled, analyze_pre_trade_sentiment, _get_ai_settings

async def main():
    print("==============================================")
    print("      FXBOT AI Configuration & Connection     ")
    print("==============================================")
    
    settings = _get_ai_settings()
    provider = settings.get("ai_provider", "gemini")
    model = settings.get("ai_model", "gemini-2.0-flash")
    api_key = settings.get("ai_api_key", "").strip()
    budget = float(settings.get("ai_monthly_budget", "5.0"))
    spend = float(settings.get("ai_spend_mtd", "0.0"))
    
    print(f"- Provider:        {provider.upper()}")
    print(f"- Model:           {model}")
    print(f"- Monthly Budget:  ${budget:.2f}")
    print(f"- Spend MTD:       ${spend:.4f}")
    
    if not api_key:
        print("\n[!] ERROR: No API key is configured. Please open the Dashboard -> Settings and save your API key.")
        return
        
    masked_key = (api_key[:6] + "..." + api_key[-4:]) if len(api_key) > 10 else "***"
    print(f"- API Key:         {masked_key} (Set)")
    
    if spend >= budget:
        print("\n[!] ERROR: Monthly AI spend has reached the budget cap. Reset spend in settings or increase the budget.")
        return
        
    enabled = is_ai_enabled()
    print(f"- AI Enabled:      {enabled}")
    
    print("\n[i] Running live test request (analyzing mock news for EURUSD)...")
    res = await analyze_pre_trade_sentiment("EURUSD", "BUY")
    
    print("\n=== Response Result ===")
    print(f"- Sentiment:        {res.get('sentiment')}")
    print(f"- Confidence:       {res.get('confidence')}")
    print(f"- Score Adjustment: {res.get('score_adjustment')}")
    print(f"- Summary:          {res.get('summary')}")
    
    summary_lower = res.get('summary', '').lower()
    if "error" in summary_lower or "timeout" in summary_lower or "unavailable" in summary_lower:
        print("\n[!] Connection Test Failed! Check the summary above for the error details.")
    else:
        print("\n[+] Success! The AI connection test succeeded. Your AI co-pilot is fully functional.")
    print("==============================================")

if __name__ == "__main__":
    asyncio.run(main())
