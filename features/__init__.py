"""Features package — moi tinh nang (plugin) cua X-Bot la MOT thu muc con.

Vi du: features/readmail/ la tinh nang doc mail Hotmail/Outlook.

Them tinh nang moi:
  1. Tao thu muc features/<ten>/ voi:
       - handlers.py: `router = Router(...)`, dang ky lenh/callback, cuoi file goi
         FeatureRegistry.register(name, description, commands, router)
       - __init__.py: `from features.<ten> import handlers  # noqa: F401`
  2. Them 1 dong `import features.<ten>` trong run.py.
  3. Vao admin -> Bot -> gan tinh nang cho bot muon dung (BotFeature).
"""
