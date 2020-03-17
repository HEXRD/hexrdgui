set(CPACK_CMAKE_GENERATOR "Unix Makefiles")
set(CPACK_RESOURCE_FILE_LICENSE "${CMAKE_CURRENT_LIST_DIR}/../LICENSE.txt")
set(CPACK_PACKAGE_INSTALL_DIRECTORY "hexrd")
set(CPACK_PACKAGE_DESCRIPTION_FILE "description.txt")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "Qt5 PySide2 based HEXRD GUI")
set(CPACK_PACKAGE_EXECUTABLES "hexrd" "HEXRD")
set(CPACK_PACKAGE_NAME "HEXRD")
set(CPACK_PACKAGE_VENDOR "Kitware")
set(CPACK_PACKAGE_VERSION "0.7.1")
set(CPACK_PACKAGE_VERSION_MAJOR "0")
set(CPACK_PACKAGE_VERSION_MINOR "7")
set(CPACK_PACKAGE_VERSION_PATCH "1")
set(CPACK_PACKAGE_FILE_NAME "${CPACK_PACKAGE_NAME}-${CPACK_PACKAGE_VERSION}")
set(CPACK_INSTALL_COMMANDS "python package.py")
set(CPACK_INSTALLED_DIRECTORIES "${CMAKE_CURRENT_LIST_DIR}/package;/")

if (APPLE)
  set(CPACK_GENERATOR "DragNDrop")
  set(CPACK_DMG_DS_STORE_SETUP_SCRIPT "${CMAKE_CURRENT_LIST_DIR}/darwin/CMakeDMGSetup.scpt")
  set(CPACK_DMG_BACKGROUND_IMAGE "${CMAKE_CURRENT_LIST_DIR}/darwin/CMakeDMGBackground.tif")
elseif(WIN32)
  set(CPACK_GENERATOR "WIX")
  set(CPACK_WIX_PROPERTY_ARPURLINFOABOUT "https://github.com/hexrd/hexrdgui")

  set(CPACK_WIX_PROPERTY_ARPCONTACT "hexrd@kitware.com")

  set(CPACK_WIX_PROPERTY_ARPCOMMENTS
    "Qt5 PySide2 based HEXRD GUI."
    )

#  set(CPACK_WIX_PRODUCT_ICON
#    "@CMAKE_CURRENT_LIST_DIR@/InstallerIcon.ico"
#    )

#  set(CPACK_WIX_UI_BANNER
#    "@CMAKE_CURRENT_LIST_DIR@/ui_banner.jpg"
#    )

#  set(CPACK_WIX_UI_DIALOG
#    "@CMAKE_CURRENT_LIST_DIR@/ui_dialog.jpg"
#    )

  set(CPACK_WIX_UPGRADE_GUID "5F369ED0-05D7-4CBA-B533-D1A1B3F445C3")
  set(CPACK_WIX_TEMPLATE "${CMAKE_CURRENT_LIST_DIR}/windows/WIX.template.in")
  #set(CPACK_WIX_EXTRA_SOURCES "${CMAKE_CURRENT_LIST_DIR}/windows/shortcuts.wxs")
    # We set this because it normally defaults to CMAKE_SIZEOF_VOID_P, but we aren't
  # running CMake here!
  set(CPACK_WIX_SIZEOF_VOID_P 8)
  set(CPACK_PACKAGE_INSTALL_DIRECTORY "HEXRD")
  set(CPACK_CREATE_DESKTOP_LINKS "HEXRD" "HEXRD")
else()
  set(CPACK_GENERATOR "TGZ")
endif()
