# bizagi-agent-poc

اثبات مفهوم (فاز صفر): ایجنتی که یک فرآیند خرید کامل (مدل داده، فرم‌ها، قوانین، نقش‌ها) را به‌صورت خودکار داخل Bizagi Studio می‌سازد.

## وضعیت

| مرحله | ماژول | وضعیت | سیستم‌عامل |
|---|---|---|---|
| مشخصات ساختاریافتهٔ فرآیند | `src/design_layer/spec_schema.py` | ✅ آماده | همه |
| نمونهٔ خرید با ۳ سطح تأیید | `src/design_layer/sample_purchase.py` | ✅ آماده | همه |
| خروجی BPMN 2.0 (معتبر طبق XSD رسمی OMG) | `src/bpmn/bpmn_builder.py` | ✅ آماده + تست | همه |
| پیش‌نمایش HTML (نمودار، مدل داده، فرم‌های راست‌چین، قوانین) | `src/bpmn/preview.py` | ✅ آماده | همه |
| تأیید read-only از SQL Server | `src/verify/sql_verify.py` | ⏳ بعدی | ویندوز |
| کشف AutomationIdها و لایهٔ UIA | `src/uia/*` | ⏳ بعدی | ویندوز + Bizagi Studio |
| planner (زبان طبیعی → ProcessSpec) | `src/design_layer/planner.py` | ⏳ بعدی | همه |

## اجرا

```bash
python3 -m venv .venv && source .venv/bin/activate   # ویندوز: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest              # تست‌ها، شامل اعتبارسنجی XML با XSD رسمی BPMN 2.0
python -m src.run_poc         # خروجی در پوشهٔ out/
```

خروجی‌ها:
- `out/PurchaseRequestProcess.bpmn` — در Bizagi Modeler از مسیر Import → BPMN باز می‌شود.
- `out/preview.html` — بدون اینترنت و بدون Bizagi در هر مرورگری باز می‌شود؛ نمودار SVG ثابت است و در چاپ/PDF/اسکرین‌شات کامل هم دیده می‌شود.
- `out/spec.json` — مشخصات کامل فرآیند که لایهٔ UIA از آن می‌سازد.

یک نسخهٔ آماده از همین خروجی‌ها در `examples/` هست.

## فرآیند نمونه

ثبت درخواست (درخواست‌کننده) ← تأیید مدیر واحد ← تأیید مدیر مالی ← تأیید مدیرعامل ← انجام خرید (کارشناس تدارکات). رد در هر سطح به پایان «درخواست رد شد» می‌رود و ثبت توضیح را الزامی می‌کند.

- همهٔ فیلدهای تاریخ شمسی‌اند (schema تقویم دیگری را نمی‌پذیرد).
- برچسب‌ها فارسی و نام‌های فنی ASCII هستند (نام فنی همان نام موجودیت/فیلد در Bizagi است).
- کد قوانین به نحو عبارات Bizagi نوشته شده و باید روی ویرایشگر قانونِ Studio 11.2.5 بررسی شود.

## مجوزها

`tests/schemas/bpmn20/` شامل XSDهای رسمی BPMN 2.0 (OMG) است.
