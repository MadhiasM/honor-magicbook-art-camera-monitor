# TODO

- logging (like in version 2)
- C or JS instead of Python
- Camera Icon
  - Storage Slot:
    - Attached: Grey
    - Detached: Grey / 5 Sec
  - Camera Slot:
    - Attached: Blue / 6 Sec
    - Detached: Grey
  - No Camera Detected (Warning): Red / After 6 Sec/1 Sec after Detached Notification. 
- Hide "Just now" Timestamp
- Either hide "Honor Camera" or remove "Camera" from text output (reduntant information)
- Multi Language Support
- Fix persistent Camera Disconnect notification 
- Remove hardcoded path
- Create Service
- Create isntructions
  - sudo usermod -aG input mathias so no root needed
  - Deploy Service
# Done
- Any new banner should override present banner
- Icon (mono)
- Warning if Camera is neither in the storage slot not on the camera slot after n seconds debouncing
    - This should be persistent but removed once either the storage or camera slot is filled again
- Initial scan of existing devices additionally to add/remove listen (if camera is already plugged in) (Really necessary?)
