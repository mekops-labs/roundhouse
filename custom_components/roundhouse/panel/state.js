// The model of the panel: the latest snapshot and the live states.

export function emptyModel() {
  return { snapshot: null, states: {}, icons: {} };
}

// Apply one message of the subscription to the model; returns a new model.
export function reduce(model, message) {
  if (message.type === "snapshot") {
    const { states, icons, ...snapshot } = message;
    return { snapshot, states: { ...states }, icons: { ...icons } };
  }
  if (message.type === "state") {
    return {
      snapshot: model.snapshot,
      states: { ...model.states, [message.entity_id]: message.state },
      icons: { ...model.icons, ...message.icons },
    };
  }
  return model;
}

export function tileState(model, entityId) {
  return model.states[entityId] ?? null;
}
