import React from 'react';
import { registerRootComponent } from 'expo';
import { useFonts } from 'expo-font';

import App from './App';

function Root() {
  const [loaded, error] = useFonts({
    Quicksand: require('./assets/fonts/Quicksand.ttf'),
  });
  if (!loaded && !error) return null;
  return React.createElement(App);
}

registerRootComponent(Root);
