'use strict';
// Demo-only API responses: no API request leaves the browser and no forms are saved.
(() => {
  const member = {name:'Alex',status:'accepted',wishes:'Ein gutes Buch oder etwas für den Garten.',address:''};
  const participants = ['Alex','Lina','Sam'].map((name,i)=>({id:i+1,name,email:name.toLowerCase()+'@example.invalid',status:i===2?'pending':'accepted',mail_status:'not_sent',mailed:null}));
  const common = {date:'2026-12-24',budget:'25 €',invitation:'Ein schöner Abend, ein kleines Geschenk und Zeit füreinander.',postal:false,public_code:null,retention:24,expires:null,membership:member,exclusions:[],participants};
  const events = [
    {...common,id:'demo-owner',title:'Wichteln im Freundeskreis',owner:1,organizer:true,drawn:false,recipient:null},
    {...common,id:'demo-guest',title:'Wichteln im Team',owner:2,organizer:false,drawn:true,recipient:{id:2,name:'Lina',wishes:'Ein Notizbuch, Kräutertee oder ein kleines Puzzle.',address:''}}
  ];
  const english = () => window.WWI18N.language === 'en';
  const message = () => english()
    ? 'Demo: forms are not saved and no emails are sent. Please use fictional details only.'
    : 'Demo: Formulare werden nicht gespeichert und keine E-Mails versendet. Bitte nur Beispieldaten verwenden.';
  window.fetch = async (input, options={}) => {
    const path = new URL(input,location.href).pathname;
    let data, status=200;
    if (path==='/api/me') {
      const guest = !location.hash || location.hash==='#login';
      data={user:guest?null:{id:1,name:'Alex',email:'alex@example.invalid',language:window.WWI18N.language},csrf:'demo-only',can_create_events:true};
    } else if (path==='/api/language') data={ok:true};
    else if ((options.method||'GET')!=='GET') {data={error:message()};status=403;}
    else if (path==='/api/events') data={events};
    else {
      data=events.find(event=>path==='/api/events/'+event.id);
      if (!data) {data={error:message()};status=404;}
    }
    return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
  };
  const banner=document.createElement('aside');
  banner.id='demo-banner';
  banner.className='card soft';
  banner.style.cssText='max-width:1120px;margin:1rem auto;padding:1rem';
  function updateBanner() {
    const labels=english()?['Home','Rounds','Organizer','Participant','New round']:['Startseite','Runden','Organisation','Teilnahme','Neue Runde'];
    const routes=['','#dashboard','#event=demo-owner','#event=demo-guest','#new'];
    banner.innerHTML=`<p><strong>Demo</strong> · ${english()?'No emails or saved form data. Use fictional details only.':'Keine E-Mails oder gespeicherten Formulardaten. Bitte nur Beispieldaten verwenden.'}</p><nav class="actions" aria-label="Demo">${routes.map((route,i)=>`<a class="button secondary small" href="${route||'#'}">${labels[i]}</a>`).join('')}</nav>`;
  }
  document.querySelector('.site-header').after(banner);
  window.addEventListener('ww:languagechange',updateBanner);
  updateBanner();
})();
