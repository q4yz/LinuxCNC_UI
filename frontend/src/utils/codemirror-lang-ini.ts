import { StreamLanguage } from '@codemirror/language'
import { properties } from '@codemirror/legacy-modes/mode/properties'

export const ini = () => StreamLanguage.define(properties)
