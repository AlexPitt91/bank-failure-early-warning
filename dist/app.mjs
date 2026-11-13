const byId = id => document.getElementById(id);
const number = new Intl.NumberFormat('en-US');
const percent = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 });
const dateLabel = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeZone: 'UTC' });
const fmtDate = value => dateLabel.format(new Date(value));

function element(tag, value, className) {
  const item = document.createElement(tag);
  if (value != null) item.textContent = value;
  if (className) item.className = className;
  return item;
}

function metric(label, value) {
  const card = element('div', null, 'metric');
  card.append(element('span', label), element('strong', value));
  return card;
}

function formatFeature(index, value) {
  if (value == null) return 'Unavailable';
  if (index === 2) return percent.format(value / 100);
  if (index === 5) return number.format(Math.round(Math.exp(value))) + ' thousand USD';
  return percent.format(value);
}

function bankDetails(bank, rank, model, features, revealed) {
  const panel = byId('details');
  panel.replaceChildren(element('h2', bank.name), element('p', 'Review rank ' + rank + ' · FDIC certificate ' + bank.cert));
  if (revealed) {
    panel.append(element('p', bank.failure ? 'Failed ' + fmtDate(bank.failure) : 'No recorded failure in the review window', 'outcome'));
  }
  if (model === 'baseline') {
    panel.append(element('p', 'This rule ranks banks with lower equity relative to assets first.'));
  } else {
    panel.append(element('h3', 'Largest score changes'));
    const list = element('ul');
    for (const [index, impact] of bank[model]) {
      const magnitude = Math.abs(impact * 100).toFixed(2);
      const change = impact === 0 ? 'no measurable change' : (impact > 0 ? '+' : '−') + magnitude + ' score points';
      list.append(element('li', features[index] + ' · ' + change));
    }
    panel.append(list, element('p', 'Each change compares the observed input with its training median.', 'quiet'));
  }
  panel.append(element('h3', 'Reported indicators'));
  const list = element('dl');
  features.forEach((feature, index) => {
    list.append(element('dt', index === 5 ? 'Total assets' : feature), element('dd', formatFeature(index, bank.values[index])));
  });
  panel.append(list);
}

async function start() {
  const response = await fetch('./replay.json');
  if (!response.ok) throw new Error('Replay snapshot unavailable');
  const data = await response.json();
  const dates = Object.keys(data.cohorts);
  const models = Object.entries(data.models);
  const features = Object.values(data.features);
  const date = byId('date');
  const model = byId('model');
  const budget = byId('budget');
  const reveal = byId('reveal');
  let revealed = false;
  let activeCert;

  dates.forEach(value => date.add(new Option(fmtDate(value), value)));
  date.value = dates.includes('2023-03-01') ? '2023-03-01' : dates.at(-1);
  models.forEach(([id, name]) => model.add(new Option(name, id)));
  model.value = data.selected;
  for (const [id, name] of models) {
    const result = data.results[id];
    const cells = [name + (id === data.selected ? ' (selected)' : ''),
      result.caught + ' / ' + result.failures, percent.format(result.precision),
      percent.format(result.average_precision),
      result.median_lead_days == null ? 'Unavailable' : result.median_lead_days + ' days'];
    const row = element('tr');
    cells.forEach(value => row.append(element('td', value)));
    byId('results').append(row);
  }

  function render() {
    const modelIndex = models.findIndex(([id]) => id === model.value);
    const cohort = data.cohorts[date.value];
    const ranked = [...cohort.banks].sort((a, b) => a.ranks[modelIndex] - b.ranks[modelIndex]);
    const alerts = ranked.slice(0, Number(budget.value));
    const caught = alerts.filter(bank => bank.failure);
    const missed = ranked.slice(alerts.length).filter(bank => bank.failure);
    if (!alerts.some(bank => bank.cert === activeCert)) activeCert = alerts[0].cert;
    byId('summary').replaceChildren(
      metric('Banks screened', number.format(cohort.size)),
      metric('Alerts to review', number.format(alerts.length)),
      metric('Failures caught', revealed ? caught.length + ' of ' + (caught.length + missed.length) : 'Hidden'),
      metric('False alarms', revealed ? number.format(alerts.length - caught.length) : 'Hidden'),
    );
    byId('cohort-description').textContent = fmtDate(date.value) + ' · ' + data.models[model.value];
    byId('outcome-heading').hidden = !revealed;
    reveal.textContent = revealed ? 'Hide outcomes' : 'Reveal outcomes';
    reveal.setAttribute('aria-pressed', String(revealed));
    const body = byId('queue');
    body.replaceChildren();
    const buttons = [];
    alerts.forEach((bank, index) => {
      const row = element('tr');
      const name = element('td');
      const button = element('button', bank.name, 'bank');
      button.type = 'button';
      button.setAttribute('aria-pressed', String(bank.cert === activeCert));
      buttons.push(button);
      button.addEventListener('click', () => {
        activeCert = bank.cert;
        buttons.forEach(other => other.setAttribute('aria-pressed', String(other === button)));
        bankDetails(bank, index + 1, model.value, features, revealed);
      });
      name.append(button);
      row.append(element('td', index + 1), name);
      if (revealed) row.append(element('td', bank.failure ? 'Failed' : 'No failure', bank.failure ? 'hit' : 'quiet'));
      if (bank.cert === activeCert) bankDetails(bank, index + 1, model.value, features, revealed);
      body.append(row);
    });
    const missedPanel = byId('missed');
    missedPanel.hidden = !revealed;
    if (revealed) {
      const list = element('ul');
      for (const bank of missed) {
        const item = element('li');
        const button = element('button', bank.name, 'bank');
        button.type = 'button';
        const rank = bank.ranks[modelIndex];
        button.addEventListener('click', () => {
          activeCert = bank.cert;
          buttons.forEach(other => other.setAttribute('aria-pressed', 'false'));
          bankDetails(bank, rank, model.value, features, revealed);
          byId('details').focus();
        });
        item.append(button, ' · ' + fmtDate(bank.failure) + ' · Rank ' + rank);
        list.append(item);
      }
      missedPanel.replaceChildren(element('h2', 'Failures outside the alert budget'),
        missed.length ? list : element('p', 'No eligible failures were missed in this review.'));
    }
  }

  [date, model, budget].forEach(control => control.addEventListener('change', () => {
    revealed = false;
    activeCert = undefined;
    render();
  }));
  reveal.addEventListener('click', () => { revealed = !revealed; render(); });
  render();
  byId('dashboard').hidden = false;
  byId('status').hidden = true;
}

start().catch(error => {
  byId('status').textContent = 'The replay could not load. Refresh the page to try again.';
  console.error(error);
});
