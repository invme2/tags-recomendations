# -*- coding: utf-8 -*-
"""Build taxonomy/facets.json — the single source of truth for the facet/filter/Shop-by-type system.
Externalizes the rules that used to live hardcoded in pipeline/tools/gen_facets.py::derive()."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'taxonomy', 'facets.json')

# ---- categories: ORDER MATTERS (first keyword/cluster match wins) ----
# NOTE: Sexual Wellness is FIRST so explicit adult keywords win before generic body/massage/health
# rules grab them. Keywords are specific + word-boundary matched (earplug/analysis/massager don't leak in).
CATS = [
 ("Sexual Wellness",      ["vibrator","vibrators","dildo","dildos","lube","personal lubricant","intimate lubricant",
                           "condom","masturbat","butt plug","anal plug","anal toy","anal beads","anal vibrator",
                           "cock ring","penis ring","penis pump","g-spot","g spot","clitoral","clitoris",
                           "prostate massager","prostate stimulator","bondage","kegel","ben wa","strap-on","strap on",
                           "stroker","pleasure toy","adult toy","sex toy","nipple clamp","bullet vibrator",
                           "rabbit vibrator","aphrodisiac","thrusting vibrator","wearable vibrator","remote vibrator",
                           "intimate toy"],
                          ["adult","sexual-wellness","intimate","sex-toys"],
                          ["For"], ["how_to","safety","care","whats_included","target_profile"]),
 # cluster_keywords intentionally EMPTY for these new categories: the legacy cluster: taxonomy
 # wasn't built for them, so cluster matching bleeds (snoring->Respiratory, eye-makeup->Eye). Title-only.
 ("Feminine Care",        ["vaginal","feminine hygiene","feminine wash","menstrual cup","menstrual","gynecolog",
                           "yeast infection","intimate wash","yoni","period underwear"],
                          [], ["Concern","Format","For"], ["how_to","safety","ingredients","target_profile"]),
 ("Eye Care",             ["eye drops","eye spray","dry eye","dry eyes","contact lens","lens cleaner","lens case",
                           "anti-fog spray","eyeglass cleaner","eye wash","myopia"],
                          [], ["For","Format"], ["how_to","safety","target_profile"]),
 ("Ear & Hearing Care",   ["ear wax","earwax","ear cleaner","ear cleaning","ear pick","ear vacuum","tinnitus",
                           "hearing aid","hearing amplifier","sound amplifier","ear correct","ear drops","otoscope",
                           "ear care serum","ear sticker"],
                          [], ["For","Format"], ["how_to","safety","care","target_profile"]),
 ("Jewelry & Accessories",["earrings","necklace","choker","grillz","anklet","brooch","pendant","jewelry",
                           "stud earrings","crawler earrings"],
                          [], ["For"], ["care","target_profile"]),
 ("Fragrance",            ["perfume","cologne","eau de","fragrance"," scent"," musk","parfum"], ["fragrance","perfume"],
                          ["Scent","Format","For"], ["scent_profile","ingredients","gift_options","target_profile"]),
 ("Nail Care",            ["nail","acrylic","manicure","pedicure","cuticle"], ["nail"],
                          ["Format","For"], ["how_to","care","target_profile"]),
 ("Oral Care",            ["tooth","teeth","dental","oral","floss","mouth","denture","interdental"], ["oral","dental"],
                          ["Concern","Format","For"], ["ingredients","how_to","safety","target_profile"]),
 ("Makeup",               ["makeup","lipstick","mascara","eyeliner","eyeshadow","foundation","blush","lash","brow","brush","blender","sponge"], ["makeup","cosmetics","lash-brow","eye-makeup"],
                          ["Format","For"], ["variants","how_to","target_profile"]),
 ("Hair & Grooming",      ["hair","beard","shav","razor","clipper","trimmer","wig","comb","scalp"], ["hair","beard","grooming","shaving"],
                          ["Concern","Format","For"], ["how_to","ingredients","target_profile"]),
 ("Supplements & Wellness",["supplement","gummies","gummy","capsule","vitamin","collagen","probiotic","magnesium","ashwagandha","tablet","powder"], ["supplement","wellness","vitamin","gummies"],
                          ["Concern","Format","For"], ["nutrition_facts","ingredients","clinical_evidence","protocol","safety","subscription_refill","target_profile"]),
 ("Massage & Recovery",   ["massage","massager","knee","back pain","joint","foot","posture","brace","heating pad","acupressure","cupping"], ["massage","back-pain","knee","joint","foot-care","recovery"],
                          ["Concern","Format","For"], ["how_to","protocol","safety","target_profile"]),
 ("Body Care",            ["body","cellulite","slimming","sculpt","bath","shower","scrub","tan","firming"], ["body-care","body-sculpting","cellulite","bath","shower","slimming"],
                          ["Concern","Format","For"], ["ingredients","how_to","care","target_profile"]),
 ("Men's Grooming",       ["men's","mens "], [],
                          ["Concern","Format","For"], ["how_to","target_profile"]),
 ("Skincare",             ["skin","serum","cream","moistur","cleanser","acne","anti-aging","wrinkle","pore","mask","toner","spf","retinol"], ["skincare","acne","anti-aging","mens-skincare"],
                          ["Concern","Format","For"], ["ingredients","clinical_evidence","timeline","care","target_profile"]),
 ("Sleep & Snoring",      ["snore","snoring","nasal strip","sleep strip","anti-snore","apnea","mouthpiece","sleep mask","sleep aid","earplug"], [],
                          ["Concern","Format","For"], ["how_to","safety","target_profile"]),
 # --- Broad marketplace categories (incoming CSV: Fashion 130k, Electronics, Home, Auto, Pet).
 # Starter keyword rules; refine post-load via the false-positive scan (same as Sexual Wellness). ---
 ("Fashion & Apparel",    ["t-shirt","tshirt","dress","jacket","coat","hoodie","sweatshirt","pants ","trousers","jeans",
                           "sweater","cardigan","blazer","skirt","blouse","shirt","shorts","jumpsuit","leggings","socks",
                           "lingerie","underwear","bra ","panties","swimsuit","swimwear","bikini","beanie","apparel","clothing"],
                          [], ["For"], ["variants","care","target_profile"]),
 ("Electronics",          ["headphone","earphone","earbud","earbuds","power bank","powerbank","charging cable","usb cable",
                           "hdmi","webcam","camera","tablet","laptop","keyboard","mouse ","smartwatch","smart watch","projector",
                           "microphone","drone","router","bluetooth speaker","speaker"],
                          [], [], ["specs","whats_included","target_profile"]),
 ("Home & Living",        ["cookware","frying pan","cutting board","utensil","kitchen","cutlery","dinnerware","bedding","duvet",
                           "pillow","blanket","towel","curtain","rug ","doormat","vase","home decor","wall art","storage box",
                           "laundry","mop ","broom","dustpan","garden","planter","furniture","shelf","clothes hanger","trash can","tablecloth"],
                          [], [], ["specs","whats_included","care","target_profile"]),
 ("Auto & Moto",          ["car mount","car seat","car cover","windshield","windscreen","dashboard","steering wheel","license plate",
                           "car wash","car wax","motorcycle","motorbike","tire ","tyre","wiper","automotive","vehicle","car mat"],
                          [], [], ["specs","whats_included","target_profile"]),
 ("Pet Supplies",         ["pet ","dog ","puppy","kitten","cat litter","litter box","aquarium","fish tank","pet bed","dog bed",
                           "cat bed","leash","pet collar","dog collar","chew toy","bird cage","hamster","pet food","kennel","scratching post"],
                          [], ["For"], ["specs","how_to","target_profile"]),
 ("Health & Wellness",    ["brace","support","posture","radiation","protective","emergency","blood pressure","thermometer","first aid","air purifier","air fresh","humidifier","monitor","glucose","nebulizer","anti-chafing","insole","wrist","ankle","elbow","compression"], [],
                          ["Concern","Format","For"], ["specs","safety","how_to","target_profile"]),
]

# category browse-collection handles. Override where a bare slug would collide with an existing
# cluster-collection (e.g. eye-care already exists as a beauty-tools cluster collection).
HANDLE_OVERRIDE = {"Eye Care": "eye-care-wellness"}
def slug(name):
    if name in HANDLE_OVERRIDE: return HANDLE_OVERRIDE[name]
    s=name.lower()
    for a,b in [(" & ","-"),(" ","-"),("'","")]: s=s.replace(a,b)
    return s

categories={}; order=[]
for name,kw,cl,params,modules in CATS:
    order.append(name)
    categories[name]={"keywords":kw,"cluster_keywords":cl,"params":params,"modules":modules,"collection_handle":slug(name)}

PARAMS={
 "Format": {"type":"single","priority":[
    ["Gummies",["gummies","gummy"]],["Capsules",["capsule","softgel","caps "]],["Tablets",["tablet","pill "]],
    ["Powder",["powder"]],["Drops & Liquids",["drops","tincture","liquid "]],["Serum",["serum","essence","ampoule"]],
    ["Oil",[" oil","essential oil"]],["Cream & Lotion",["cream","lotion","balm","butter","moisturizer"]],["Gel",[" gel"]],
    ["Spray & Mist",["spray","mist"]],["Mask",[" mask","sheet mask"]],["Patches",["patch","patches","strips"]],
    ["Cleanser & Wash",["cleanser","wash","soap","foam","shampoo"]],
    ["Tools & Devices",["massager","device","machine","roller","gua sha","trimmer","clipper","lamp","brush","tool","kit","tweezer","file","curler","mirror","meter","monitor"]]]},
 "Concern": {"type":"multi","max":3,"values":{
    "Acne":["acne","pimple","blemish","blackhead","breakout"],"Anti-aging":["anti-aging","anti aging","wrinkle","firming"," lift","collagen","age "],
    "Brightening":["bright","whiten","dark spot","pigment","glow","radian","tone"],"Hydration":["hydrat","moistur"," dry ","nourish"],
    "Pores":["pore"],"Slimming & Contour":["cellulite","slim","fat ","contour","sculpt","weight","firm"],
    "Pain Relief":["pain"," ache","sore","relief","arthritis","inflamm"],"Sleep":["sleep","insomnia","melatonin","night"],
    "Stress & Calm":["stress","anxiety","calm","relax","ashwagandha"],"Hair Growth":["hair growth","regrow","thinning","bald","grow hair"],
    "Joint & Back":["joint","knee","back ","spine","posture","lumbar"],"Snoring":["snore","snoring","apnea"],
    "Detox":["detox","cleanse","colon"],"Energy & Focus":["energy","focus","brain","memory","cognit"],
    "Immunity":["immune","immunity","vitamin c"],"Teeth Whitening":["whiten","teeth"]}},
 "For": {"type":"single","values":{"Women":["women","ladies","female","her "],"Men":["men's","mens "," men ","male","him "],"Unisex":[]},
         "demo_map":{"female":"Women","male":"Men","unisex":"Unisex"}},
 "Scent": {"type":"multi","max":3,"category_gate":"Fragrance","values":{
    "Floral":["floral","rose","jasmine","flower","peony"],"Woody":["wood","sandal","oud","cedar","amber"],
    "Citrus":["citrus","lemon","bergamot","orange","lime","grapefruit"],"Fresh":["fresh","aqua","marine","clean","ocean","breeze"],
    "Sweet":["vanilla","sweet","caramel","gourmand","candy","sugar"],"Musk":["musk"],"Oriental & Spice":["oriental","spice","cinnamon","clove"]}},
}

config={"version":"1.0","fallback_category":"Health & Wellness","category_order":order,
        "categories":categories,"params":PARAMS,
        "llm":{"confidence_threshold":1,"model":"claude-haiku-4-5","enable":True}}

json.dump(config, open(OUT,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", OUT, "| categories:", len(order), "| params:", list(PARAMS.keys()))
