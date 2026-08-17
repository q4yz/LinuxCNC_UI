// Machineconfig module manifest. Mirrors
// ``backend/modules/machineconfig/module.py`` so the registry surfaces
// the same metadata.
//
// The sidebar id is ``machineconfig`` (matches ``manifest.id``) so the
// sidebar id and the route name agree. ``registerModuleRoutes`` in
// ``frontend/src/router/index.js`` reads this id to add the
// ``/machineconfig`` route at boot. The legacy ``/config`` editor
// route stays under the editor for direct deep-links — see
// ``router/index.js``. See ``.agent/STATE.md`` § 9 (active modules
// table).


const gearIcon = '<svg class="w-6 h-6 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>'

export default {
  id: "machineconfig",
  title: "Machine Config",
  version: "0.1.0",
  description:
    "Profiles editor, compiler selection, staged/active viewer, deployment.",
  sidebar: { id: "machineconfig", label: "Machine Config", icon: gearIcon, order: 60 },
  settingsPanel: true,
};