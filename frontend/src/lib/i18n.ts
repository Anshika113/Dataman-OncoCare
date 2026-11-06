// The patient-facing strings, in the languages this clinic's patients read.
//
// Scope is deliberate. The console stays English: the doctors, nurses and
// coordinators who use it work in English, and translating four hundred
// strings nobody asked for would be work spent on the wrong screen. The one
// surface a *patient* ever sees is the one that must not be English-only, so
// it is the one translated here — along with the guidance line, which the
// engine hands over as a key rather than as prose for exactly this reason.
//
// No library. A dictionary and a lookup are the whole requirement, and a
// 40 kB i18n framework to render one page would be a worse answer.

export type Lang = 'en' | 'hi' | 'mr'

export const LANGS: { code: Lang; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिंदी' },
  { code: 'mr', label: 'मराठी' },
]

type Dict = Record<string, string>

const en: Dict = {
  brand: 'Cancer Care',
  subtitle: 'Your appointment',
  your_number: 'Your number',
  booked_for: 'Booked for',
  with_doctor: 'With',
  treatment: 'Treatment',
  checked_in: 'Checked in',
  ahead_of_you: 'Ahead of you',

  coming_question: 'Are you coming?',
  coming_help: 'Telling us early lets someone else use the slot if you cannot.',
  yes_coming: 'Yes, I am coming',
  cannot_make: 'I cannot make it',
  previously: 'You previously answered:',
  answer_coming: 'coming',
  answer_cannot: 'cannot make it',
  thanks_coming: 'Thank you — we will expect you.',
  thanks_cannot: 'Thank you — we have let the clinic know.',
  send_failed: 'Could not send that. Please phone the clinic.',

  caregiver_title: 'For whoever came with you',
  caregiver_body: 'You can follow this page alongside the patient. It does not show any treatment details.',

  footer: 'This page updates by itself. It shows only your own visit.',
  invalid_link: 'This link is not valid.',
  unreachable: 'Could not reach the clinic. Try again in a moment.',

  'stage.not_arrived': 'Not checked in yet',
  'stage.ready': 'Checked in — waiting to be called',
  'stage.in_labs': 'Waiting for your test results',
  'stage.with_doctor': 'With the doctor now',
  'stage.done': 'Visit complete',
  'stage.cancelled': 'This appointment is cancelled',

  'advice.check_in': 'Please check in at the desk when you arrive.',
  'advice.in_labs': 'Your results are being processed. You have not lost your place.',
  'advice.ahead_one': '1 patient ahead of you — roughly {minutes} minutes.',
  'advice.ahead_other': '{ahead} patients ahead of you — roughly {minutes} minutes.',
  'advice.next': 'You are next.',
  'advice.done': 'Nothing further today.',
}

const hi: Dict = {
  brand: 'कैंसर केयर',
  subtitle: 'आपका अपॉइंटमेंट',
  your_number: 'आपका नंबर',
  booked_for: 'समय',
  with_doctor: 'डॉक्टर',
  treatment: 'इलाज',
  checked_in: 'चेक-इन',
  ahead_of_you: 'आपसे पहले',

  coming_question: 'क्या आप आ रहे हैं?',
  coming_help: 'पहले बता देने से, अगर आप नहीं आ सकते तो वह समय किसी और को मिल जाएगा।',
  yes_coming: 'हाँ, आ रहे हैं',
  cannot_make: 'नहीं आ सकते',
  previously: 'आपने पहले बताया था:',
  answer_coming: 'आ रहे हैं',
  answer_cannot: 'नहीं आ सकते',
  thanks_coming: 'धन्यवाद — हम आपका इंतज़ार करेंगे।',
  thanks_cannot: 'धन्यवाद — हमने क्लिनिक को बता दिया है।',
  send_failed: 'भेजा नहीं जा सका। कृपया क्लिनिक को फ़ोन करें।',

  caregiver_title: 'साथ आए व्यक्ति के लिए',
  caregiver_body: 'आप मरीज़ के साथ यह जानकारी देख सकते हैं। इसमें इलाज का कोई ब्योरा नहीं है।',

  footer: 'यह पेज अपने आप अपडेट होता है। इसमें सिर्फ़ आपकी ही जानकारी दिखती है।',
  invalid_link: 'यह लिंक मान्य नहीं है।',
  unreachable: 'क्लिनिक से संपर्क नहीं हो सका। कुछ देर में फिर कोशिश करें।',

  'stage.not_arrived': 'अभी चेक-इन नहीं हुआ',
  'stage.ready': 'चेक-इन हो गया — बुलाने का इंतज़ार',
  'stage.in_labs': 'आपकी जाँच की रिपोर्ट का इंतज़ार',
  'stage.with_doctor': 'अभी डॉक्टर के साथ',
  'stage.done': 'मुलाक़ात पूरी हुई',
  'stage.cancelled': 'यह अपॉइंटमेंट रद्द है',

  'advice.check_in': 'आने पर डेस्क पर चेक-इन करें।',
  'advice.in_labs': 'आपकी रिपोर्ट तैयार हो रही है। आपकी जगह सुरक्षित है।',
  'advice.ahead_one': 'आपसे पहले 1 मरीज़ है — लगभग {minutes} मिनट।',
  'advice.ahead_other': 'आपसे पहले {ahead} मरीज़ हैं — लगभग {minutes} मिनट।',
  'advice.next': 'अब आपकी बारी है।',
  'advice.done': 'आज के लिए और कुछ नहीं।',
}

const mr: Dict = {
  brand: 'कर्करोग उपचार',
  subtitle: 'तुमची अपॉइंटमेंट',
  your_number: 'तुमचा क्रमांक',
  booked_for: 'वेळ',
  with_doctor: 'डॉक्टर',
  treatment: 'उपचार',
  checked_in: 'चेक-इन',
  ahead_of_you: 'तुमच्या आधी',

  coming_question: 'तुम्ही येत आहात का?',
  coming_help: 'आधी कळवल्यास, तुम्ही येऊ शकत नसाल तर ती वेळ दुसऱ्याला देता येईल.',
  yes_coming: 'हो, येत आहे',
  cannot_make: 'येऊ शकत नाही',
  previously: 'तुम्ही आधी सांगितले होते:',
  answer_coming: 'येत आहे',
  answer_cannot: 'येऊ शकत नाही',
  thanks_coming: 'धन्यवाद — आम्ही तुमची वाट पाहत आहोत.',
  thanks_cannot: 'धन्यवाद — आम्ही क्लिनिकला कळवले आहे.',
  send_failed: 'पाठवता आले नाही. कृपया क्लिनिकला फोन करा.',

  caregiver_title: 'सोबत आलेल्या व्यक्तीसाठी',
  caregiver_body: 'तुम्ही रुग्णासोबत ही माहिती पाहू शकता. यात उपचाराचा तपशील नाही.',

  footer: 'हे पान आपोआप अद्ययावत होते. यात फक्त तुमची माहिती दिसते.',
  invalid_link: 'ही लिंक वैध नाही.',
  unreachable: 'क्लिनिकशी संपर्क होऊ शकला नाही. थोड्या वेळाने पुन्हा प्रयत्न करा.',

  'stage.not_arrived': 'अजून चेक-इन झाले नाही',
  'stage.ready': 'चेक-इन झाले — बोलावण्याची वाट',
  'stage.in_labs': 'तुमच्या तपासणीच्या अहवालाची वाट',
  'stage.with_doctor': 'आता डॉक्टरांकडे',
  'stage.done': 'भेट पूर्ण झाली',
  'stage.cancelled': 'ही अपॉइंटमेंट रद्द झाली आहे',

  'advice.check_in': 'आल्यावर डेस्कवर चेक-इन करा.',
  'advice.in_labs': 'तुमचा अहवाल तयार होत आहे. तुमची जागा कायम आहे.',
  'advice.ahead_one': 'तुमच्या आधी 1 रुग्ण आहे — अंदाजे {minutes} मिनिटे.',
  'advice.ahead_other': 'तुमच्या आधी {ahead} रुग्ण आहेत — अंदाजे {minutes} मिनिटे.',
  'advice.next': 'आता तुमची वेळ आहे.',
  'advice.done': 'आजसाठी आणखी काही नाही.',
}

const DICTS: Record<Lang, Dict> = { en, hi, mr }

export function isLang(v: any): v is Lang {
  return v === 'en' || v === 'hi' || v === 'mr'
}

/** A string in `lang`, falling back to English rather than to the key.
 *
 * A missing translation should read as slightly wrong, not as broken: a
 * patient seeing `stage.ready` on their screen is worse than seeing it in
 * English.
 */
export function t(lang: Lang, key: string, vars?: Record<string, any>): string {
  const s = DICTS[lang]?.[key] ?? en[key] ?? ''
  if (!vars) return s
  return s.replace(/\{(\w+)\}/g, (_m, k) =>
    vars[k] === undefined || vars[k] === null ? '' : String(vars[k]))
}

/** The guidance line the engine described, said in this language. */
export function advice(lang: Lang, key: string, vars?: Record<string, any>): string {
  if (!key) return ''
  if (key === 'ahead') {
    const n = Number(vars?.ahead ?? 0)
    return t(lang, n === 1 ? 'advice.ahead_one' : 'advice.ahead_other', vars)
  }
  return t(lang, `advice.${key}`, vars)
}

/** The stage name, said in this language. */
export function stage(lang: Lang, key: string, fallback = ''): string {
  return t(lang, `stage.${key}`) || fallback
}
